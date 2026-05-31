"""规则函数 — 每个规则接收 snapshot dict 并返回 RuleResult。

snapshot 结构：{indicator_name: {"value": ..., "unit": ..., ...}}

每个规则函数：
    def rule_xxx(snap: dict) -> RuleResult | None
    返回 None 表示规则不适用（缺数据或条件不满足）
    返回 RuleResult 表示规则触发

按品种导出规则列表：
    COMMON_RULES, SUGAR_RULES, PALM_RULES, RUBBER_RULES
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class RuleResult:
    rule_id: str          # 唯一 id 便于追踪
    label: str            # 中文描述
    category: str         # 分类（用于权重展示）
    score_delta: int      # 正=利多/加分，负=利空/减分
    side: str             # "bullish" / "bearish" / "neutral"
    evidence: dict        # 触发时关联的指标值，便于报告展示
    flag: Optional[str] = None  # 特殊标记，如 "资金行情"


def _val(snap: dict, key: str, default=None):
    """安全取值。"""
    entry = snap.get(key)
    if not entry:
        return default
    v = entry.get("value")
    return default if v is None else v


def _num(snap: dict, key: str, default=None) -> Optional[float]:
    v = _val(snap, key, default)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _text(snap: dict, key: str, default: str = "") -> str:
    v = _val(snap, key, default)
    return str(v) if v is not None else default


def _bool(snap: dict, key: str, default: bool = False) -> bool:
    v = _val(snap, key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "y")
    return bool(v)


def _evidence(snap: dict, *keys: str) -> dict:
    return {k: snap.get(k) for k in keys if k in snap}


# =====================================================================
# 共同 ENSO 规则
# =====================================================================
def rule_nino34_warm_high(snap):
    v = _num(snap, "nino34")
    if v is None:
        return None
    # 分级：取最高一档（避免双计）
    if v > 1.5:
        return RuleResult("enso.nino34.gt_1_5", f"Niño 3.4 = {v:.2f}°C，超过 +1.5°C，强厄尔尼诺信号",
                          "weather", +15, "bullish", _evidence(snap, "nino34"))
    if v > 1.0:
        return RuleResult("enso.nino34.gt_1_0", f"Niño 3.4 = {v:.2f}°C，超过 +1.0°C",
                          "weather", +10, "bullish", _evidence(snap, "nino34"))
    if v > 0.5:
        return RuleResult("enso.nino34.gt_0_5", f"Niño 3.4 = {v:.2f}°C，超过 +0.5°C",
                          "weather", +5, "bullish", _evidence(snap, "nino34"))
    return None


def rule_oni_3mo_above(snap):
    n = _num(snap, "oni_consecutive_months_above_0_5")
    if n is None:
        return None
    if n >= 3:
        return RuleResult("enso.oni.confirmed", f"ONI 连续 {int(n)} 个月 > +0.5°C，确认厄尔尼诺",
                          "weather", +10, "bullish",
                          _evidence(snap, "oni", "oni_consecutive_months_above_0_5"))
    return None


def rule_soi_persistently_negative(snap):
    n = _num(snap, "soi_consecutive_negative_weeks")
    if n is None:
        return None
    if n >= 4:
        return RuleResult("enso.soi.negative_streak",
                          f"SOI 连续 {int(n)} 周为负，配合 Niño 信号",
                          "weather", +5, "bullish",
                          _evidence(snap, "soi", "soi_consecutive_negative_weeks"))
    return None


COMMON_RULES: list[Callable] = [
    rule_nino34_warm_high,
    rule_oni_3mo_above,
    rule_soi_persistently_negative,
]


# =====================================================================
# 白糖规则
# =====================================================================
def rule_sugar_india_monsoon_weak(snap):
    weeks = _num(snap, "india_monsoon_below_normal_weeks")
    if weeks is None:
        return None
    if weeks >= 2:
        return RuleResult("sugar.india.monsoon_weak",
                          f"印度季风降雨连续 {int(weeks)} 周低于正常",
                          "india", +5, "bullish",
                          _evidence(snap, "india_monsoon_anomaly_pct",
                                    "india_monsoon_below_normal_weeks"))
    return None


def rule_sugar_maha_kar_dry(snap):
    m = _num(snap, "maharashtra_rainfall_anomaly_pct")
    k = _num(snap, "karnataka_rainfall_anomaly_pct")
    triggers = []
    if m is not None and m <= -20:
        triggers.append(("Maharashtra", m))
    if k is not None and k <= -20:
        triggers.append(("Karnataka", k))
    if triggers:
        names = ", ".join(f"{n}({v:.0f}%)" for n, v in triggers)
        return RuleResult("sugar.india.maha_kar_dry",
                          f"印度核心蔗区降雨低于正常 20%+：{names}",
                          "india", +10, "bullish",
                          _evidence(snap, "maharashtra_rainfall_anomaly_pct",
                                    "karnataka_rainfall_anomaly_pct"))
    return None


def rule_sugar_india_export_restriction(snap):
    p = _text(snap, "india_export_policy", "").lower()
    if any(s in p for s in ("ban", "restriction", "new_ban", "ban_extended")):
        return RuleResult("sugar.india.export_restriction",
                          f"印度糖出口政策收紧 ({p})",
                          "india", +15, "bullish",
                          _evidence(snap, "india_export_policy"))
    return None


def rule_sugar_india_production_downgrade(snap):
    d = _num(snap, "india_sugar_production_change_mt")
    if d is None:
        return None
    if d <= -1.0:
        return RuleResult("sugar.india.production_down_big",
                          f"印度糖产量预估下调 {abs(d):.2f} 百万吨 (>100 万吨)",
                          "india", +15, "bullish",
                          _evidence(snap, "india_sugar_production_mt",
                                    "india_sugar_production_change_mt"))
    return None


def rule_sugar_brazil_crush_yoy_down(snap):
    v = _num(snap, "brazil_cs_crush_yoy_pct")
    if v is None:
        return None
    if v < 0:
        return RuleResult("sugar.brazil.crush_yoy_down",
                          f"巴西中南部压榨量同比 {v:.1f}%",
                          "brazil", +5, "bullish",
                          _evidence(snap, "brazil_cs_crush_yoy_pct"))
    return None


def rule_sugar_brazil_sugar_mix_down(snap):
    v = _num(snap, "brazil_sugar_mix_change_pp")
    if v is None:
        return None
    if v <= -2:
        return RuleResult("sugar.brazil.mix_down",
                          f"巴西糖醇比下降 {abs(v):.1f}pp",
                          "brazil", +10, "bullish",
                          _evidence(snap, "brazil_sugar_mix_pct",
                                    "brazil_sugar_mix_change_pp"))
    return None


def rule_sugar_brazil_oil_ethanol_up(snap):
    brent_up = _num(snap, "brent_consecutive_up_days", 0) or 0
    eth_up = _num(snap, "brazil_ethanol_consecutive_up_days", 0) or 0
    if brent_up >= 3 and eth_up >= 2:
        return RuleResult("sugar.brazil.oil_ethanol_up",
                          f"原油连涨 {int(brent_up)}日 + 巴西乙醇连涨 {int(eth_up)}日",
                          "brazil", +10, "bullish",
                          _evidence(snap, "brent_price_usd",
                                    "brent_consecutive_up_days",
                                    "brazil_ethanol_price_brl"))
    return None


def rule_sugar_thai_dry_persistent(snap):
    w = _num(snap, "thailand_rainfall_below_normal_weeks")
    if w is None:
        return None
    if w >= 4:
        return RuleResult("sugar.thai.dry_4w",
                          f"泰国降雨连续 {int(w)} 周偏少",
                          "thailand", +10, "bullish",
                          _evidence(snap, "thailand_rainfall_anomaly_pct",
                                    "thailand_rainfall_below_normal_weeks"))
    return None


def rule_sugar_thai_production_downgrade(snap):
    d = _num(snap, "thailand_sugar_production_change_mt")
    if d is None:
        return None
    if d <= -0.5:
        return RuleResult("sugar.thai.production_down",
                          f"泰国糖产量预估下调 {abs(d):.2f} 百万吨 (>50 万吨)",
                          "thailand", +10, "bullish",
                          _evidence(snap, "thailand_sugar_production_mt",
                                    "thailand_sugar_production_change_mt"))
    return None


def rule_sugar_eu_beet_area_down(snap):
    v = _num(snap, "eu_beet_area_change_pct")
    if v is None:
        return None
    if v < 0:
        return RuleResult("sugar.eu.beet_area_down",
                          f"欧盟甜菜种植面积下降 {abs(v):.1f}%",
                          "china_eu", +5, "bullish",
                          _evidence(snap, "eu_beet_area_ha",
                                    "eu_beet_area_change_pct"))
    return None


def rule_sugar_china_gx_yn_event(snap):
    e = _text(snap, "china_guangxi_yunnan_weather_event", "normal").lower()
    if e in ("drought", "frost", "flood", "severe"):
        return RuleResult("sugar.china.gx_yn_event",
                          f"中国广西/云南出现 {e}",
                          "china_eu", +5, "bullish",
                          _evidence(snap, "china_guangxi_yunnan_weather_event"))
    return None


SUGAR_RULES: list[Callable] = [
    rule_sugar_india_monsoon_weak,
    rule_sugar_maha_kar_dry,
    rule_sugar_india_export_restriction,
    rule_sugar_india_production_downgrade,
    rule_sugar_brazil_crush_yoy_down,
    rule_sugar_brazil_sugar_mix_down,
    rule_sugar_brazil_oil_ethanol_up,
    rule_sugar_thai_dry_persistent,
    rule_sugar_thai_production_downgrade,
    rule_sugar_eu_beet_area_down,
    rule_sugar_china_gx_yn_event,
]


# =====================================================================
# 棕榈油规则（含负值）
# =====================================================================
def rule_palm_indo_dry(snap):
    w = _num(snap, "indonesia_core_rainfall_below_normal_weeks")
    if w is None:
        return None
    if w >= 4:
        return RuleResult("palm.indo.dry_4w",
                          f"印尼核心油棕区连续 {int(w)} 周降雨低于正常 20%",
                          "indonesia", +10, "bullish",
                          _evidence(snap, "sumatra_rainfall_anomaly_pct",
                                    "kalimantan_rainfall_anomaly_pct"))
    return None


def rule_palm_indo_b50(snap):
    p = _text(snap, "indonesia_biodiesel_mandate", "").lower()
    if p in ("b50_announced", "b50_implementing"):
        return RuleResult("palm.indo.b50_advance",
                          f"印尼 B50 政策推进 ({p})",
                          "biodiesel_oil", +15, "bullish",
                          _evidence(snap, "indonesia_biodiesel_mandate"))
    if p in ("b50_postponed", "b50_cancelled"):
        return RuleResult("palm.indo.b50_retreat",
                          f"印尼 B50 推迟或取消 ({p})",
                          "biodiesel_oil", -15, "bearish",
                          _evidence(snap, "indonesia_biodiesel_mandate"))
    return None


def rule_palm_indo_export_restriction(snap):
    p = _text(snap, "indonesia_export_policy", "").lower()
    if any(s in p for s in ("dmo_tighten", "export_tax_up",
                            "export_restriction", "export_ban")):
        return RuleResult("palm.indo.export_restrict",
                          f"印尼棕油出口收紧 ({p})",
                          "indonesia", +10, "bullish",
                          _evidence(snap, "indonesia_export_policy"))
    return None


def rule_palm_indo_production_downgrade(snap):
    d = _num(snap, "indonesia_cpo_production_change_mt")
    if d is None:
        return None
    if d <= -1.0:
        return RuleResult("palm.indo.production_down_big",
                          f"印尼 CPO 产量预估下调 {abs(d):.2f} 百万吨 (>100 万吨)",
                          "indonesia", +15, "bullish",
                          _evidence(snap, "indonesia_cpo_production_mt",
                                    "indonesia_cpo_production_change_mt"))
    return None


def rule_palm_mpob_stock_levels(snap):
    """库存分档：<160 +15 (取代 <180), 180-160 +8, >220 -10。"""
    s = _num(snap, "mpob_end_stock_mt")
    if s is None:
        return None
    # 单位是 million MT
    if s < 1.60:
        return RuleResult("palm.mpob.stock_lt_160",
                          f"马来月末库存 {s:.2f} 百万吨 (<160 万吨)",
                          "malaysia", +15, "bullish",
                          _evidence(snap, "mpob_end_stock_mt"))
    if s < 1.80:
        return RuleResult("palm.mpob.stock_lt_180",
                          f"马来月末库存 {s:.2f} 百万吨 (<180 万吨)",
                          "malaysia", +8, "bullish",
                          _evidence(snap, "mpob_end_stock_mt"))
    if s > 2.20:
        return RuleResult("palm.mpob.stock_gt_220",
                          f"马来月末库存 {s:.2f} 百万吨 (>220 万吨)",
                          "malaysia", -10, "bearish",
                          _evidence(snap, "mpob_end_stock_mt"))
    return None


def rule_palm_mpob_production_below_seasonal(snap):
    p = _num(snap, "mpob_cpo_production_mt")
    avg = _num(snap, "mpob_cpo_production_5y_avg_mt")
    if p is None or avg is None or avg == 0:
        return None
    if p < avg:
        return RuleResult("palm.mpob.production_below_seasonal",
                          f"马来月产量 {p:.2f} 低于 5 年同月均值 {avg:.2f}",
                          "malaysia", +8, "bullish",
                          _evidence(snap, "mpob_cpo_production_mt",
                                    "mpob_cpo_production_5y_avg_mt"))
    return None


def rule_palm_mpob_export_up_stock_down(snap):
    e = _num(snap, "mpob_export_mom_change_pct")
    s = _num(snap, "mpob_stock_mom_change_pct")
    if e is None or s is None:
        return None
    if e > 0 and s < 0:
        return RuleResult("palm.mpob.export_up_stock_down",
                          f"马来出口环比 +{e:.1f}%、库存环比 {s:.1f}%",
                          "malaysia", +10, "bullish",
                          _evidence(snap, "mpob_export_mt",
                                    "mpob_export_mom_change_pct",
                                    "mpob_end_stock_mt",
                                    "mpob_stock_mom_change_pct"))
    return None


def rule_palm_brent_sustained_up(snap):
    d = _num(snap, "brent_consecutive_up_days", 0) or 0
    px = _num(snap, "brent_price_usd")
    if d >= 5 and (px is None or px >= 75):
        return RuleResult("palm.brent.sustained_up",
                          f"Brent 连涨 {int(d)} 日，价格 {px}",
                          "biodiesel_oil", +8, "bullish",
                          _evidence(snap, "brent_price_usd",
                                    "brent_consecutive_up_days"))
    return None


def rule_palm_substitute_oils_up(snap):
    so = _num(snap, "soybean_oil_consecutive_up_days", 0) or 0
    ro = _num(snap, "rapeseed_oil_consecutive_up_days", 0) or 0
    su = _num(snap, "sunflower_oil_consecutive_up_days", 0) or 0
    if so >= 2 and ro >= 2 and su >= 1:
        return RuleResult("palm.substitute_oils_up",
                          "豆油、菜油、葵油同步上涨",
                          "substitute_oil", +8, "bullish",
                          _evidence(snap, "soybean_oil_price_usd",
                                    "rapeseed_oil_price_usd",
                                    "sunflower_oil_price_usd"))
    return None


def rule_palm_import_demand_recovery(snap):
    cn = _num(snap, "china_palm_import_mom_change_pct", 0) or 0
    ind = _num(snap, "india_palm_import_mom_change_pct", 0) or 0
    if cn >= 5 or ind >= 5:
        return RuleResult("palm.import_recovery",
                          f"中国/印度棕油进口恢复 (中{cn:.1f}% / 印{ind:.1f}%)",
                          "demand_in_cn", +8, "bullish",
                          _evidence(snap, "china_palm_import_mt",
                                    "india_palm_import_mt",
                                    "china_palm_import_mom_change_pct",
                                    "india_palm_import_mom_change_pct"))
    return None


def rule_palm_mpob_stock_surge(snap):
    s = _num(snap, "mpob_stock_mom_change_pct")
    if s is None:
        return None
    if s >= 30:
        return RuleResult("palm.mpob.stock_surge",
                          f"马来库存大幅累积 (环比 +{s:.1f}%)",
                          "malaysia", -15, "bearish",
                          _evidence(snap, "mpob_end_stock_mt",
                                    "mpob_stock_mom_change_pct"))
    return None


PALM_RULES: list[Callable] = [
    rule_palm_indo_dry,
    rule_palm_indo_b50,
    rule_palm_indo_export_restriction,
    rule_palm_indo_production_downgrade,
    rule_palm_mpob_stock_levels,
    rule_palm_mpob_production_below_seasonal,
    rule_palm_mpob_export_up_stock_down,
    rule_palm_brent_sustained_up,
    rule_palm_substitute_oils_up,
    rule_palm_import_demand_recovery,
    rule_palm_mpob_stock_surge,
]


# =====================================================================
# 橡胶规则（含负值 + 资金行情标记）
# =====================================================================
def rule_rubber_thai_latex_up(snap):
    d = _num(snap, "thai_field_latex_consecutive_up_days")
    if d is None:
        return None
    if d >= 5:
        return RuleResult("rubber.thai.latex_up_5d",
                          f"泰国胶水连续 {int(d)} 日上涨",
                          "asean_supply", +10, "bullish",
                          _evidence(snap, "thai_field_latex_price_thb",
                                    "thai_field_latex_consecutive_up_days"))
    return None


def rule_rubber_thai_cuplump_up(snap):
    d = _num(snap, "thai_cup_lump_consecutive_up_days")
    if d is None:
        return None
    if d >= 3:
        return RuleResult("rubber.thai.cuplump_up",
                          f"泰国杯胶连续 {int(d)} 日上涨",
                          "asean_supply", +5, "bullish",
                          _evidence(snap, "thai_cup_lump_price_thb",
                                    "thai_cup_lump_consecutive_up_days"))
    return None


def rule_rubber_thai_south_extreme(snap):
    e = _text(snap, "thailand_south_extreme_event", "normal").lower()
    if e in ("heavy_rain", "drought", "flood"):
        return RuleResult("rubber.thai.south_extreme",
                          f"泰国南部 {e} 影响割胶",
                          "asean_supply", +10, "bullish",
                          _evidence(snap, "thailand_south_rainfall_anomaly_pct",
                                    "thailand_south_extreme_event"))
    return None


def rule_rubber_anrpc_downgrade(snap):
    d = _num(snap, "anrpc_forecast_change_kt")
    if d is None:
        return None
    if d < 0:
        return RuleResult("rubber.anrpc.downgrade",
                          f"ANRPC 下调全球产量 {abs(d):.0f} kt",
                          "asean_supply", +15, "bullish",
                          _evidence(snap, "anrpc_production_forecast_kt",
                                    "anrpc_forecast_change_kt"))
    return None


def rule_rubber_tire_op_rate_up(snap):
    s = _num(snap, "china_semi_steel_op_rate_change_pct", 0) or 0
    f = _num(snap, "china_full_steel_op_rate_change_pct", 0) or 0
    if s > 0 and f > 0:
        return RuleResult("rubber.china.tire_op_up",
                          f"半钢 +{s:.1f}% 与全钢 +{f:.1f}% 开工同步上升",
                          "china_demand", +10, "bullish",
                          _evidence(snap, "china_semi_steel_tire_operating_rate_pct",
                                    "china_full_steel_tire_operating_rate_pct"))
    return None


def rule_rubber_china_tire_export_yoy_up(snap):
    v = _num(snap, "china_tire_export_yoy_pct")
    if v is None:
        return None
    if v > 0:
        return RuleResult("rubber.china.tire_export_yoy_up",
                          f"中国轮胎出口同比 +{v:.1f}%",
                          "china_demand", +5, "bullish",
                          _evidence(snap, "china_tire_export_yoy_pct"))
    return None


def rule_rubber_china_import_up_stock_down(snap):
    imp = _num(snap, "china_natural_rubber_import_mom_pct", 0) or 0
    qd = _num(snap, "qingdao_bonded_stock_change_pct", 0) or 0
    if imp > 0 and qd < 0:
        return RuleResult("rubber.china.import_up_stock_down",
                          f"中国天胶进口环比 +{imp:.1f}% & 库存 {qd:.1f}%",
                          "china_demand", +10, "bullish",
                          _evidence(snap, "china_natural_rubber_import_mt",
                                    "china_natural_rubber_import_mom_pct",
                                    "qingdao_bonded_stock_kt",
                                    "qingdao_bonded_stock_change_pct"))
    return None


def rule_rubber_qingdao_stock_down(snap):
    v = _num(snap, "qingdao_bonded_stock_change_pct")
    if v is None:
        return None
    if v < 0:
        return RuleResult("rubber.inv.qingdao_down",
                          f"青岛保税库存 {v:.1f}%",
                          "inventory", +10, "bullish",
                          _evidence(snap, "qingdao_bonded_stock_kt",
                                    "qingdao_bonded_stock_change_pct"))
    return None


def rule_rubber_shfe_ine_stock_down(snap):
    ru = _num(snap, "shfe_ru_stock_change_pct")
    nr = _num(snap, "ine_nr20_stock_change_pct")
    if (ru is not None and ru < 0) or (nr is not None and nr < 0):
        which = []
        if ru is not None and ru < 0:
            which.append(f"上期所 RU {ru:.1f}%")
        if nr is not None and nr < 0:
            which.append(f"INE NR20 {nr:.1f}%")
        return RuleResult("rubber.inv.shfe_ine_down",
                          " / ".join(which),
                          "inventory", +5, "bullish",
                          _evidence(snap, "shfe_ru_stock_kt",
                                    "shfe_ru_stock_change_pct",
                                    "ine_nr20_stock_kt",
                                    "ine_nr20_stock_change_pct"))
    return None


def rule_rubber_oil_synth_up(snap):
    b = _num(snap, "brent_consecutive_up_days", 0) or 0
    bd = _num(snap, "butadiene_consecutive_up_days", 0) or 0
    br = _num(snap, "br_consecutive_up_days", 0) or 0
    if b >= 3 and bd >= 2 and br >= 2:
        return RuleResult("rubber.oil_synth.up",
                          "Brent + 丁二烯 + 合成胶同步上涨",
                          "oil_synth", +10, "bullish",
                          _evidence(snap, "brent_price_usd",
                                    "butadiene_price_usd",
                                    "br_synthetic_price_usd"))
    return None


def rule_rubber_oil_up_demand_down(snap):
    b = _num(snap, "brent_consecutive_up_days", 0) or 0
    s = _num(snap, "china_semi_steel_op_rate_change_pct", 0) or 0
    f = _num(snap, "china_full_steel_op_rate_change_pct", 0) or 0
    qd = _num(snap, "qingdao_bonded_stock_change_pct", 0) or 0
    if b >= 5 and (s < 0 or f < 0) and qd > 0:
        return RuleResult("rubber.oil_up_demand_down",
                          "原油大涨但轮胎走弱且库存上升",
                          "china_demand", -10, "bearish",
                          _evidence(snap, "brent_consecutive_up_days",
                                    "china_semi_steel_op_rate_change_pct",
                                    "china_full_steel_op_rate_change_pct",
                                    "qingdao_bonded_stock_change_pct"))
    return None


def rule_rubber_tire_op_down_stock_up(snap):
    s = _num(snap, "china_semi_steel_op_rate_change_pct")
    f = _num(snap, "china_full_steel_op_rate_change_pct")
    qd = _num(snap, "qingdao_bonded_stock_change_pct")
    if s is None or f is None or qd is None:
        return None
    if s < 0 and f < 0 and qd > 0:
        return RuleResult("rubber.tire_op_down_stock_up",
                          "轮胎开工下降且库存上升",
                          "china_demand", -15, "bearish",
                          _evidence(snap, "china_semi_steel_op_rate_change_pct",
                                    "china_full_steel_op_rate_change_pct",
                                    "qingdao_bonded_stock_change_pct"))
    return None


def rule_rubber_futures_money_flow_flag(snap):
    """期货上涨但现货不涨、库存不降 -> 标记'资金行情'，不加分。"""
    flag = _bool(snap, "nr_futures_up_but_spot_flat")
    if flag:
        return RuleResult("rubber.flag.money_flow",
                          "期货上涨但现货不涨、库存不降，疑似资金行情",
                          "policy_fx", 0, "neutral",
                          _evidence(snap, "nr_futures_up_but_spot_flat",
                                    "spot_premium_discount_yuan"),
                          flag="资金行情，持续性存疑")
    return None


RUBBER_RULES: list[Callable] = [
    rule_rubber_thai_latex_up,
    rule_rubber_thai_cuplump_up,
    rule_rubber_thai_south_extreme,
    rule_rubber_anrpc_downgrade,
    rule_rubber_tire_op_rate_up,
    rule_rubber_china_tire_export_yoy_up,
    rule_rubber_china_import_up_stock_down,
    rule_rubber_qingdao_stock_down,
    rule_rubber_shfe_ine_stock_down,
    rule_rubber_oil_synth_up,
    rule_rubber_oil_up_demand_down,
    rule_rubber_tire_op_down_stock_up,
    rule_rubber_futures_money_flow_flag,
]


# =====================================================================
# 注册表 — scoring.py 通过 RULES_BY_COMMODITY 取规则
# =====================================================================
RULES_BY_COMMODITY: dict[str, list[Callable]] = {
    "sugar": COMMON_RULES + SUGAR_RULES,
    "palm": COMMON_RULES + PALM_RULES,
    "rubber": COMMON_RULES + RUBBER_RULES,
}
