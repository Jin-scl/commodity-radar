"""评分聚合层 —— 输入 snapshot dict，输出 0-100 final_score + 等级 + 变化 + 因子。"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from src.indicators.rules import RULES_BY_COMMODITY, RuleResult, run_rule
from src.utils import get_logger, load_config
from src.storage.database import Database, today_str

logger = get_logger()


def _classify(score: int, levels: list[dict]) -> tuple[str, str, str]:
    for lvl in levels:
        if lvl["min"] <= score <= lvl["max"]:
            return lvl["level"], lvl["label"], lvl.get("desc", "")
    return "unknown", "未知", ""


def _conclude(score: int, change_1d: Optional[int],
              change_7d: Optional[int],
              price_confirmation: Optional[dict] = None) -> str:
    """生成中性结论文字（绝不出现买卖）。
    融入价格确认状态，让结论更接近"风险雷达"而非"指标清单"。
    """
    parts = []
    if score >= 71:
        parts.append("整体偏多，风险信号集中")
    elif score >= 51:
        parts.append("偏多")
    elif score >= 31:
        parts.append("中性偏多")
    elif score >= 0:
        parts.append("中性")
    if change_1d is not None:
        if change_1d >= 10:
            parts.append("当日风险显著上升")
        elif change_1d >= 5:
            parts.append("风险上升")
        elif change_1d <= -10:
            parts.append("当日风险显著下降")
        elif change_1d <= -5:
            parts.append("风险下降")
    if change_7d is not None and change_7d >= 20:
        parts.append("近 7 日累计风险上升较快，需要继续验证")
    # 价格确认融入：基本面有方向时（>=31）总是融入；
    # 基本面低分但价格领先时也融入，以保留"价格先行"信号
    if price_confirmation:
        status = price_confirmation.get("status")
        msg = price_confirmation.get("message")
        if msg and (score >= 31 or status in ("price_leading", "price_watch")):
            parts.append(msg)
    return "；".join(parts) or "中性，需要继续验证"


# =====================================================================
# 价格确认模块
# =====================================================================
# 每个品种用一组价格信号判定"价格是否确认基本面方向"。
# 不直接参与 final_score，输出独立的 confirmation status。
PRICE_SIGNALS: dict[str, list[dict]] = {
    "sugar": [
        {"name": "ice_raw_sugar_change_pct_5d",
         "weight": 2.0, "label": "ICE 11号原糖 5日变化", "threshold": 0.5},
        {"name": "london_white_sugar_change_pct_5d",
         "weight": 1.5, "label": "伦敦5号白糖 5日变化", "threshold": 0.5},
        # 雷亚尔贬值（USD/BRL ↑）= 巴西糖出口竞争力增强 = 利空国际糖价
        # 因此与"基本面偏多"是 diverging；invert 取负号
        {"name": "usd_brl_change_pct_5d",
         "weight": 1.0, "label": "USD/BRL 雷亚尔 5日变化", "threshold": 0.3,
         "invert": True},
    ],
    "palm": [
        {"name": "bmd_palm_oil_change_pct_5d",
         "weight": 2.0, "label": "BMD 棕榈油 5日变化", "threshold": 0.5},
        # 近月强于远月（spread 上升）= 偏紧；反向放映现货紧张
        {"name": "bmd_calendar_spread_change_5d",
         "weight": 1.0, "label": "BMD 近远月价差 5日变化", "threshold": 5},
        # 豆棕价差扩大 = 棕油相对便宜，需求替代提升（看绝对值变化方向）
        # 这里粗简化：价差正且不缩小视为偏多确认
        {"name": "biodiesel_margin_usd",
         "weight": 0.8, "label": "生柴利润", "threshold": 0},
    ],
    "rubber": [
        {"name": "shfe_ru_change_pct_5d",
         "weight": 2.0, "label": "上期所 RU 5日变化", "threshold": 0.5},
        {"name": "ine_nr20_change_pct_5d",
         "weight": 1.5, "label": "INE 20号胶 5日变化", "threshold": 0.5},
        # 现货升水（正）= 现货强 = 偏多确认
        {"name": "spot_premium_discount_yuan",
         "weight": 1.0, "label": "现货升贴水", "threshold": 50},
    ],
}


def _compute_price_confirmation(commodity: str, final_score: int,
                                snapshot: dict,
                                cfg: Optional[dict] = None) -> dict:
    """根据 final_score 方向与价格信号判定确认状态。

    v3 升级：
    - 信号权重 × 数据置信度系数（manual medium 不等同 yfinance high）
    - 基本面低分时不再直接 neutral：若价格信号已强烈偏多/偏空 → price_leading
    - 输出 price_confirmation_confidence

    返回 {status, message, weighted_pct, signals, confidence_score}
      status: confirmed / partial / weak / diverging / price_leading /
              price_watch / no_data / neutral
    """
    cfg = cfg or load_config()
    mult_map = _get_confidence_mult(cfg)
    sig_cfg = PRICE_SIGNALS.get(commodity, [])
    signals: list[dict] = []
    conf_scores: list[int] = []
    for s_cfg in sig_cfg:
        entry = snapshot.get(s_cfg["name"])
        if not entry or entry.get("value") in (None, ""):
            continue
        try:
            val = float(entry["value"])
        except (TypeError, ValueError):
            continue
        eff_val = -val if s_cfg.get("invert") else val
        threshold = float(s_cfg.get("threshold", 0.5))
        if eff_val > threshold:
            side = "up"
        elif eff_val < -threshold:
            side = "down"
        else:
            side = "flat"
        conf = entry.get("confidence") or "medium"
        signals.append({
            "name": s_cfg["name"],
            "label": s_cfg["label"],
            "value": val,
            "side": side,
            "weight": float(s_cfg.get("weight", 1.0)),
            "confidence": conf,
            "confidence_mult": mult_map.get(conf, 0.5),
        })
        conf_scores.append(_confidence_int(conf))

    if not signals:
        return {"status": "no_data",
                "message": "缺少价格数据，确认状态未知",
                "weighted_pct": None, "signals": [],
                "confidence_score": None}

    # 计算加权方向得分（信号权重 × 置信度系数）
    weighted = 0.0
    total = 0.0
    for s in signals:
        w_eff = s["weight"] * s["confidence_mult"]
        if s["side"] == "up":
            weighted += w_eff
        elif s["side"] == "down":
            weighted -= w_eff
        total += w_eff
    pct = (weighted / total) if total else 0.0
    pct_int = int(round(pct * 100))
    pc_conf = int(sum(conf_scores) / len(conf_scores))

    if final_score < 31:
        # v3：基本面中性时，仍尊重价格信号
        if pct >= 0.5:
            status = "price_leading"
            msg = "价格领先偏多，但基本面尚未确认"
        elif pct <= -0.5:
            status = "price_leading"
            msg = "价格领先偏空，但基本面尚未确认"
        elif abs(pct) >= 0.2:
            status = "price_watch"
            msg = "价格出现微弱倾向，建议持续观察"
        else:
            status = "neutral"
            msg = "基本面与价格均中性"
    else:
        # 基本面有方向，看价格是否确认
        if pct >= 0.5:
            status, msg = "confirmed", "价格已确认基本面方向"
        elif pct > 0:
            status, msg = "partial", "价格部分确认基本面"
        elif pct > -0.5:
            status, msg = "weak", "价格确认偏弱，需要继续验证"
        else:
            status, msg = "diverging", "价格与基本面背离，持续性存疑"

    return {"status": status, "message": msg,
            "weighted_pct": pct_int, "signals": signals,
            "confidence_score": pc_conf}


# 默认评分参数（可被 config.yaml::scoring 覆盖）
_DEFAULT_CONFIDENCE_MULT = {"high": 1.0, "medium": 0.8, "low": 0.4, "none": 0.0}
_DEFAULT_CATEGORY_CAP = 25

# 兼容旧 import（测试用）
CONFIDENCE_MULT = dict(_DEFAULT_CONFIDENCE_MULT)
CATEGORY_CAP = _DEFAULT_CATEGORY_CAP


def _get_confidence_mult(cfg: dict) -> dict:
    user = (cfg.get("scoring", {}) or {}).get("confidence_mult", {}) or {}
    out = dict(_DEFAULT_CONFIDENCE_MULT)
    out.update({k: float(v) for k, v in user.items()})
    return out


def _get_category_cap(cfg: dict, commodity: str, category: str) -> int:
    caps = (cfg.get("scoring", {}) or {}).get("category_caps", {}) or {}
    c_caps = caps.get(commodity)
    if isinstance(c_caps, dict) and category in c_caps:
        return int(c_caps[category])
    return int(caps.get("default", _DEFAULT_CATEGORY_CAP))


def _rule_confidence(rule_res: RuleResult, snapshot: dict,
                     mult_map: Optional[dict] = None) -> tuple[str, float]:
    """规则置信度按 input_keys 中所有 indicator 的最低 confidence 取值。
    缺失的 input_key 视为 'none'（最严苛），避免规则"假装高置信度"。"""
    mult_map = mult_map or _DEFAULT_CONFIDENCE_MULT
    confs: list[str] = []
    keys = list(rule_res.input_keys or ())
    if not keys:
        # 兜底：用 evidence（排除内部 _ 前缀字段）
        keys = [k for k in (rule_res.evidence or {}).keys()
                if not k.startswith("_")]
    for ind_name in keys:
        entry = snapshot.get(ind_name)
        if not entry or entry.get("value") in (None, ""):
            confs.append("none")
        else:
            confs.append(entry.get("confidence") or "medium")
    if not confs:
        return "high", 1.0
    worst = min(confs, key=lambda c: mult_map.get(c, 0.5))
    return worst, mult_map.get(worst, 0.5)


def _confidence_int(conf: str) -> int:
    return {"high": 100, "medium": 70, "low": 30, "none": 0}.get(conf, 60)


def _overall_confidence(snapshot: dict) -> int:
    """所有 indicator 置信度的均值（0-100），用于报告整体展示。"""
    if not snapshot:
        return 0
    total = 0
    n = 0
    for entry in snapshot.values():
        c = (entry or {}).get("confidence") or "medium"
        total += _confidence_int(c)
        n += 1
    return int(total / n) if n else 0


def _triggered_confidence(triggered: list[RuleResult], snapshot: dict) -> int:
    """触发规则的 input_key 最低置信度均值；更能反映"真正推动分数的数据质量"。"""
    if not triggered:
        return 100  # 没触发即没风险，置信度满分
    vals = []
    for r in triggered:
        keys = list(r.input_keys or ())
        confs = []
        for k in keys:
            entry = snapshot.get(k)
            if not entry or entry.get("value") in (None, ""):
                confs.append("none")
            else:
                confs.append(entry.get("confidence") or "medium")
        if confs:
            worst = min(confs, key=lambda c: _confidence_int(c))
            vals.append(_confidence_int(worst))
    return int(sum(vals) / len(vals)) if vals else 100


def evaluate_commodity(commodity: str, snapshot: dict,
                       db: Optional[Database] = None,
                       score_date: Optional[str] = None,
                       config: Optional[dict] = None) -> dict:
    """对单一品种计算评分结果。

    评分流程（v2 升级）：
    1) 跑所有规则，收集 RuleResult
    2) 对每条规则按 evidence 的最低 confidence 衰减 delta
       high=1.0, medium=0.8, low=0.4
    3) 按 category 聚合 delta，每个 category 总贡献 clamp 到 [-CATEGORY_CAP, +CATEGORY_CAP]
       （避免同一风险被多条规则重复奖励）
    4) raw_score = Σ category_capped_deltas
    5) final_score = clamp(raw_score, 0, 100)
    6) 计算整体 confidence_score (0-100) 用于报告
    7) 与昨日/上周分数对比（change_1d / change_7d）
    8) 与昨日触发规则 id 集合 diff（factor_diff: added/removed/persistent）

    snapshot: {indicator_name: {value, unit, confidence, ...}} (扁平结构)
    """
    cfg = config or load_config()
    score_date = score_date or today_str()
    rules = RULES_BY_COMMODITY.get(commodity, [])
    triggered: list[RuleResult] = []

    for rule_fn in rules:
        try:
            res = run_rule(rule_fn, snapshot)  # 自动收集 input_keys
        except Exception as e:
            res = None
            logger.warning("[rule error] %s %s: %s",
                           commodity, rule_fn.__name__, e)
        if res is not None:
            triggered.append(res)

    # 置信度衰减（按 input_keys 真实判定字段；缺失字段视为 'none' → ×0）
    mult_map = _get_confidence_mult(cfg)
    for r in triggered:
        original = r.score_delta
        worst, mult = _rule_confidence(r, snapshot, mult_map=mult_map)
        r.score_delta = int(round(original * mult))
        r.evidence["_rule_confidence"] = worst
        r.evidence["_original_delta"] = original

    # Category 聚合 + 封顶（按 config.scoring.category_caps 可精细化）
    category_raw: dict[str, int] = {}
    for r in triggered:
        category_raw.setdefault(r.category, 0)
        category_raw[r.category] += r.score_delta
    category_capped: dict[str, int] = {}
    for k, v in category_raw.items():
        cap = _get_category_cap(cfg, commodity, k)
        category_capped[k] = max(-cap, min(cap, v))

    raw_score = sum(category_capped.values())
    final_score = max(0, min(100, raw_score))
    level, label, _ = _classify(final_score, cfg["risk_levels"])

    confidence_score = _overall_confidence(snapshot)
    triggered_confidence = _triggered_confidence(triggered, snapshot)

    bullish = [asdict(r) for r in triggered if r.side == "bullish"]
    bearish = [asdict(r) for r in triggered if r.side == "bearish"]
    flags = [asdict(r) for r in triggered if r.flag]
    triggered_ids = [r.rule_id for r in triggered]

    # 历史对比
    change_1d = None
    change_7d = None
    prev1 = None
    prev7 = None
    factor_diff = {"added": [], "removed": [], "persistent": triggered_ids}
    if db is not None:
        prev1 = db.get_score_n_days_ago(commodity, 1, score_date)
        prev7 = db.get_score_n_days_ago(commodity, 7, score_date)
        if prev1:
            change_1d = final_score - int(prev1["final_score"])
            # diff 昨日触发规则集合
            try:
                import json as _json
                prev_ids = set(_json.loads(prev1.get("triggered_rules_json") or "[]"))
            except Exception:
                prev_ids = set()
            curr_ids = set(triggered_ids)
            factor_diff = {
                "added": sorted(curr_ids - prev_ids),
                "removed": sorted(prev_ids - curr_ids),
                "persistent": sorted(curr_ids & prev_ids),
            }
        if prev7:
            change_7d = final_score - int(prev7["final_score"])

    # 等级穿越检测（用于报告标注；预警在 dispatcher 单独判定）
    regime_change = None
    if db is not None and prev1 and prev1.get("risk_level") != level:
        regime_change = {
            "from": prev1["risk_level_label"],
            "to": label,
            "direction": "up" if final_score > int(prev1["final_score"]) else "down",
        }

    # 价格确认（独立维度，不参与 final_score；融入 conclusion 文字）
    price_confirmation = _compute_price_confirmation(commodity, final_score,
                                                      snapshot, cfg=cfg)
    conclusion = _conclude(final_score, change_1d, change_7d,
                           price_confirmation=price_confirmation)

    return {
        "commodity": commodity,
        "score_date": score_date,
        "raw_score": raw_score,
        "final_score": final_score,
        "risk_level": level,
        "risk_level_label": label,
        "confidence_score": confidence_score,
        "triggered_confidence": triggered_confidence,
        "price_confirmation": price_confirmation,
        "score_change_1d": change_1d,
        "score_change_7d": change_7d,
        "bullish_factors": bullish,
        "bearish_factors": bearish,
        "neutral_flags": flags,
        "triggered_count": len(triggered),
        "triggered_rules": triggered_ids,
        "category_breakdown": category_capped,
        "category_raw": category_raw,
        "factor_diff": factor_diff,
        "regime_change": regime_change,
        "conclusion": conclusion,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }


def evaluate_all(snapshots: dict[str, dict],
                 db: Optional[Database] = None,
                 score_date: Optional[str] = None,
                 config: Optional[dict] = None) -> dict[str, dict]:
    """snapshots: {commodity: snapshot_dict}"""
    out = {}
    for commodity, snap in snapshots.items():
        out[commodity] = evaluate_commodity(commodity, snap, db, score_date, config)
    return out


def persist_scores(results: dict[str, dict], db: Database,
                   alerts: dict[str, list] | None = None) -> None:
    """把 evaluate_all 的结果写入 scores 表。"""
    alerts = alerts or {}
    for commodity, r in results.items():
        db.save_score({
            "commodity": commodity,
            "score_date": r["score_date"],
            "raw_score": r["raw_score"],
            "final_score": r["final_score"],
            "risk_level": r["risk_level"],
            "risk_level_label": r["risk_level_label"],
            "confidence_score": r.get("confidence_score"),
            "score_change_1d": r.get("score_change_1d"),
            "score_change_7d": r.get("score_change_7d"),
            "bullish_json": r.get("bullish_factors", []),
            "bearish_json": r.get("bearish_factors", []),
            "triggered_alerts_json": alerts.get(commodity, []),
            "triggered_rules_json": r.get("triggered_rules", []),
            "payload_json": {
                "conclusion": r["conclusion"],
                "category_breakdown": r["category_breakdown"],
                "category_raw": r.get("category_raw", {}),
                "neutral_flags": r.get("neutral_flags", []),
                "triggered_count": r["triggered_count"],
                "factor_diff": r.get("factor_diff", {}),
                "regime_change": r.get("regime_change"),
                "price_confirmation": r.get("price_confirmation"),
            },
        })
