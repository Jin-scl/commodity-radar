"""规则函数单元测试：每条规则正反两个场景。"""
from __future__ import annotations

from src.indicators import rules


def _snap(**kwargs) -> dict:
    """构造 snapshot：把 key=value 包装成 {value: ...} 结构。"""
    return {k: {"value": v} for k, v in kwargs.items()}


# ---------- ENSO ----------
def test_nino34_warm_high_triggers_at_1_5():
    r = rules.rule_nino34_warm_high(_snap(nino34=1.6))
    assert r and r.score_delta == 15

def test_nino34_warm_high_triggers_at_1_0():
    r = rules.rule_nino34_warm_high(_snap(nino34=1.2))
    assert r and r.score_delta == 10

def test_nino34_warm_high_triggers_at_0_5():
    r = rules.rule_nino34_warm_high(_snap(nino34=0.6))
    assert r and r.score_delta == 5

def test_nino34_warm_high_neutral_no_trigger():
    assert rules.rule_nino34_warm_high(_snap(nino34=0.2)) is None

def test_oni_3mo_confirmed():
    r = rules.rule_oni_3mo_above(_snap(oni_consecutive_months_above_0_5=3))
    assert r and r.score_delta == 10

def test_oni_2mo_no_trigger():
    assert rules.rule_oni_3mo_above(_snap(oni_consecutive_months_above_0_5=2)) is None

def test_soi_negative_streak():
    r = rules.rule_soi_persistently_negative(_snap(soi_consecutive_negative_weeks=5))
    assert r and r.score_delta == 5

def test_soi_short_streak_no_trigger():
    assert rules.rule_soi_persistently_negative(
        _snap(soi_consecutive_negative_weeks=2)) is None


# ---------- 白糖 ----------
def test_sugar_india_monsoon_weak_triggers():
    r = rules.rule_sugar_india_monsoon_weak(_snap(india_monsoon_below_normal_weeks=2))
    assert r and r.score_delta == 5

def test_sugar_india_monsoon_one_week_no_trigger():
    assert rules.rule_sugar_india_monsoon_weak(
        _snap(india_monsoon_below_normal_weeks=1)) is None

def test_sugar_maha_dry_triggers():
    r = rules.rule_sugar_maha_kar_dry(_snap(maharashtra_rainfall_anomaly_pct=-25))
    assert r and r.score_delta == 10

def test_sugar_maha_kar_normal_no_trigger():
    assert rules.rule_sugar_maha_kar_dry(_snap(
        maharashtra_rainfall_anomaly_pct=-10, karnataka_rainfall_anomaly_pct=-5)) is None

def test_sugar_india_export_ban_triggers():
    r = rules.rule_sugar_india_export_restriction(_snap(india_export_policy="ban_extended"))
    assert r and r.score_delta == 15

def test_sugar_india_export_open_no_trigger():
    assert rules.rule_sugar_india_export_restriction(
        _snap(india_export_policy="open")) is None

def test_sugar_india_prod_downgrade_triggers():
    r = rules.rule_sugar_india_production_downgrade(_snap(india_sugar_production_change_mt=-1.5))
    assert r and r.score_delta == 15

def test_sugar_india_prod_small_change_no_trigger():
    assert rules.rule_sugar_india_production_downgrade(
        _snap(india_sugar_production_change_mt=-0.5)) is None

def test_sugar_brazil_crush_yoy_down_triggers():
    r = rules.rule_sugar_brazil_crush_yoy_down(_snap(brazil_cs_crush_yoy_pct=-3.0))
    assert r and r.score_delta == 5

def test_sugar_brazil_crush_yoy_up_no_trigger():
    assert rules.rule_sugar_brazil_crush_yoy_down(
        _snap(brazil_cs_crush_yoy_pct=1.0)) is None

def test_sugar_brazil_mix_down_triggers():
    r = rules.rule_sugar_brazil_sugar_mix_down(_snap(brazil_sugar_mix_change_pp=-2.5))
    assert r and r.score_delta == 10

def test_sugar_brazil_mix_minor_no_trigger():
    assert rules.rule_sugar_brazil_sugar_mix_down(
        _snap(brazil_sugar_mix_change_pp=-1.0)) is None

def test_sugar_brazil_oil_ethanol_up_triggers():
    r = rules.rule_sugar_brazil_oil_ethanol_up(_snap(
        brent_consecutive_up_days=4, brazil_ethanol_consecutive_up_days=2))
    assert r and r.score_delta == 10

def test_sugar_brazil_oil_ethanol_short_no_trigger():
    assert rules.rule_sugar_brazil_oil_ethanol_up(_snap(
        brent_consecutive_up_days=2, brazil_ethanol_consecutive_up_days=2)) is None

def test_sugar_thai_dry_4w_triggers():
    r = rules.rule_sugar_thai_dry_persistent(_snap(thailand_rainfall_below_normal_weeks=4))
    assert r and r.score_delta == 10

def test_sugar_thai_dry_2w_no_trigger():
    assert rules.rule_sugar_thai_dry_persistent(
        _snap(thailand_rainfall_below_normal_weeks=2)) is None

def test_sugar_thai_prod_downgrade_triggers():
    r = rules.rule_sugar_thai_production_downgrade(_snap(thailand_sugar_production_change_mt=-0.8))
    assert r and r.score_delta == 10

def test_sugar_thai_prod_small_no_trigger():
    assert rules.rule_sugar_thai_production_downgrade(
        _snap(thailand_sugar_production_change_mt=-0.2)) is None

def test_sugar_eu_beet_area_down_triggers():
    r = rules.rule_sugar_eu_beet_area_down(_snap(eu_beet_area_change_pct=-2.0))
    assert r and r.score_delta == 5

def test_sugar_eu_beet_area_up_no_trigger():
    assert rules.rule_sugar_eu_beet_area_down(_snap(eu_beet_area_change_pct=1.0)) is None

def test_sugar_china_gx_yn_event_triggers():
    r = rules.rule_sugar_china_gx_yn_event(_snap(china_guangxi_yunnan_weather_event="drought"))
    assert r and r.score_delta == 5

def test_sugar_china_gx_yn_normal_no_trigger():
    assert rules.rule_sugar_china_gx_yn_event(
        _snap(china_guangxi_yunnan_weather_event="normal")) is None


# ---------- 棕榈油 ----------
def test_palm_indo_dry_4w_triggers():
    r = rules.rule_palm_indo_dry(_snap(indonesia_core_rainfall_below_normal_weeks=4))
    assert r and r.score_delta == 10

def test_palm_indo_dry_2w_no_trigger():
    assert rules.rule_palm_indo_dry(
        _snap(indonesia_core_rainfall_below_normal_weeks=2)) is None

def test_palm_indo_b50_advance_positive():
    r = rules.rule_palm_indo_b50(_snap(indonesia_biodiesel_mandate="B50_announced"))
    assert r and r.score_delta == 15 and r.side == "bullish"

def test_palm_indo_b50_postponed_negative():
    r = rules.rule_palm_indo_b50(_snap(indonesia_biodiesel_mandate="B50_postponed"))
    assert r and r.score_delta == -15 and r.side == "bearish"

def test_palm_indo_b40_no_trigger():
    assert rules.rule_palm_indo_b50(_snap(indonesia_biodiesel_mandate="B40")) is None

def test_palm_indo_export_restrict_triggers():
    r = rules.rule_palm_indo_export_restriction(_snap(indonesia_export_policy="DMO_tightened"))
    assert r and r.score_delta == 10

def test_palm_indo_export_normal_no_trigger():
    assert rules.rule_palm_indo_export_restriction(
        _snap(indonesia_export_policy="no_change")) is None

def test_palm_indo_prod_downgrade_big_triggers():
    r = rules.rule_palm_indo_production_downgrade(_snap(indonesia_cpo_production_change_mt=-1.2))
    assert r and r.score_delta == 15

def test_palm_indo_prod_small_change_no_trigger():
    assert rules.rule_palm_indo_production_downgrade(
        _snap(indonesia_cpo_production_change_mt=-0.5)) is None

def test_palm_mpob_stock_lt_160_triggers_15():
    r = rules.rule_palm_mpob_stock_levels(_snap(mpob_end_stock_mt=1.55))
    assert r and r.score_delta == 15

def test_palm_mpob_stock_between_160_180_triggers_8():
    r = rules.rule_palm_mpob_stock_levels(_snap(mpob_end_stock_mt=1.70))
    assert r and r.score_delta == 8

def test_palm_mpob_stock_high_negative():
    r = rules.rule_palm_mpob_stock_levels(_snap(mpob_end_stock_mt=2.30))
    assert r and r.score_delta == -10

def test_palm_mpob_stock_normal_no_trigger():
    assert rules.rule_palm_mpob_stock_levels(_snap(mpob_end_stock_mt=2.0)) is None

def test_palm_mpob_prod_below_seasonal_triggers():
    r = rules.rule_palm_mpob_production_below_seasonal(_snap(
        mpob_cpo_production_mt=1.5, mpob_cpo_production_5y_avg_mt=1.7))
    assert r and r.score_delta == 8

def test_palm_mpob_prod_above_seasonal_no_trigger():
    assert rules.rule_palm_mpob_production_below_seasonal(_snap(
        mpob_cpo_production_mt=1.8, mpob_cpo_production_5y_avg_mt=1.7)) is None

def test_palm_export_up_stock_down_triggers():
    r = rules.rule_palm_mpob_export_up_stock_down(_snap(
        mpob_export_mom_change_pct=5, mpob_stock_mom_change_pct=-3))
    assert r and r.score_delta == 10

def test_palm_export_down_no_trigger():
    assert rules.rule_palm_mpob_export_up_stock_down(_snap(
        mpob_export_mom_change_pct=-1, mpob_stock_mom_change_pct=-3)) is None

def test_palm_brent_sustained_up_triggers():
    r = rules.rule_palm_brent_sustained_up(_snap(
        brent_consecutive_up_days=5, brent_price_usd=85))
    assert r and r.score_delta == 8

def test_palm_brent_short_streak_no_trigger():
    assert rules.rule_palm_brent_sustained_up(_snap(
        brent_consecutive_up_days=3, brent_price_usd=85)) is None

def test_palm_substitute_oils_up_triggers():
    r = rules.rule_palm_substitute_oils_up(_snap(
        soybean_oil_consecutive_up_days=2,
        rapeseed_oil_consecutive_up_days=2,
        sunflower_oil_consecutive_up_days=1))
    assert r and r.score_delta == 8

def test_palm_substitute_oils_mixed_no_trigger():
    assert rules.rule_palm_substitute_oils_up(_snap(
        soybean_oil_consecutive_up_days=2,
        rapeseed_oil_consecutive_up_days=1,
        sunflower_oil_consecutive_up_days=1)) is None

def test_palm_import_recovery_china_triggers():
    r = rules.rule_palm_import_demand_recovery(_snap(
        china_palm_import_mom_change_pct=8, india_palm_import_mom_change_pct=0))
    assert r and r.score_delta == 8

def test_palm_import_flat_no_trigger():
    assert rules.rule_palm_import_demand_recovery(_snap(
        china_palm_import_mom_change_pct=1, india_palm_import_mom_change_pct=0)) is None

def test_palm_stock_surge_negative():
    r = rules.rule_palm_mpob_stock_surge(_snap(mpob_stock_mom_change_pct=35))
    assert r and r.score_delta == -15

def test_palm_stock_small_change_no_trigger():
    assert rules.rule_palm_mpob_stock_surge(_snap(mpob_stock_mom_change_pct=10)) is None


# ---------- 橡胶 ----------
def test_rubber_thai_latex_up_5d_triggers():
    r = rules.rule_rubber_thai_latex_up(_snap(thai_field_latex_consecutive_up_days=5))
    assert r and r.score_delta == 10

def test_rubber_thai_latex_3d_no_trigger():
    assert rules.rule_rubber_thai_latex_up(
        _snap(thai_field_latex_consecutive_up_days=3)) is None

def test_rubber_thai_cuplump_up_triggers():
    r = rules.rule_rubber_thai_cuplump_up(_snap(thai_cup_lump_consecutive_up_days=3))
    assert r and r.score_delta == 5

def test_rubber_thai_cuplump_short_no_trigger():
    assert rules.rule_rubber_thai_cuplump_up(
        _snap(thai_cup_lump_consecutive_up_days=1)) is None

def test_rubber_thai_south_extreme_triggers():
    r = rules.rule_rubber_thai_south_extreme(_snap(thailand_south_extreme_event="heavy_rain"))
    assert r and r.score_delta == 10

def test_rubber_thai_south_normal_no_trigger():
    assert rules.rule_rubber_thai_south_extreme(
        _snap(thailand_south_extreme_event="normal")) is None

def test_rubber_anrpc_downgrade_triggers():
    r = rules.rule_rubber_anrpc_downgrade(_snap(anrpc_forecast_change_kt=-100))
    assert r and r.score_delta == 15

def test_rubber_anrpc_flat_no_trigger():
    assert rules.rule_rubber_anrpc_downgrade(_snap(anrpc_forecast_change_kt=0)) is None

def test_rubber_tire_op_up_triggers():
    r = rules.rule_rubber_tire_op_rate_up(_snap(
        china_semi_steel_op_rate_change_pct=1.5,
        china_full_steel_op_rate_change_pct=1.0))
    assert r and r.score_delta == 10

def test_rubber_tire_op_one_down_no_trigger():
    assert rules.rule_rubber_tire_op_rate_up(_snap(
        china_semi_steel_op_rate_change_pct=-0.5,
        china_full_steel_op_rate_change_pct=1.0)) is None

def test_rubber_china_tire_export_yoy_up_triggers():
    r = rules.rule_rubber_china_tire_export_yoy_up(_snap(china_tire_export_yoy_pct=6))
    assert r and r.score_delta == 5

def test_rubber_china_tire_export_yoy_down_no_trigger():
    assert rules.rule_rubber_china_tire_export_yoy_up(
        _snap(china_tire_export_yoy_pct=-1)) is None

def test_rubber_import_up_stock_down_triggers():
    r = rules.rule_rubber_china_import_up_stock_down(_snap(
        china_natural_rubber_import_mom_pct=4,
        qingdao_bonded_stock_change_pct=-2))
    assert r and r.score_delta == 10

def test_rubber_qingdao_stock_down_triggers():
    r = rules.rule_rubber_qingdao_stock_down(_snap(qingdao_bonded_stock_change_pct=-2))
    assert r and r.score_delta == 10

def test_rubber_qingdao_stock_up_no_trigger():
    assert rules.rule_rubber_qingdao_stock_down(_snap(qingdao_bonded_stock_change_pct=1)) is None

def test_rubber_shfe_down_triggers():
    r = rules.rule_rubber_shfe_ine_stock_down(_snap(
        shfe_ru_stock_change_pct=-1, ine_nr20_stock_change_pct=0))
    assert r and r.score_delta == 5

def test_rubber_shfe_ine_up_no_trigger():
    assert rules.rule_rubber_shfe_ine_stock_down(_snap(
        shfe_ru_stock_change_pct=1, ine_nr20_stock_change_pct=1)) is None

def test_rubber_oil_synth_up_triggers():
    r = rules.rule_rubber_oil_synth_up(_snap(
        brent_consecutive_up_days=3, butadiene_consecutive_up_days=2,
        br_consecutive_up_days=2))
    assert r and r.score_delta == 10

def test_rubber_oil_synth_partial_no_trigger():
    assert rules.rule_rubber_oil_synth_up(_snap(
        brent_consecutive_up_days=3, butadiene_consecutive_up_days=0,
        br_consecutive_up_days=2)) is None

def test_rubber_oil_up_demand_down_negative():
    r = rules.rule_rubber_oil_up_demand_down(_snap(
        brent_consecutive_up_days=5,
        china_semi_steel_op_rate_change_pct=-1,
        china_full_steel_op_rate_change_pct=-0.5,
        qingdao_bonded_stock_change_pct=2))
    assert r and r.score_delta == -10

def test_rubber_oil_up_demand_stable_no_trigger():
    assert rules.rule_rubber_oil_up_demand_down(_snap(
        brent_consecutive_up_days=5,
        china_semi_steel_op_rate_change_pct=1,
        china_full_steel_op_rate_change_pct=1,
        qingdao_bonded_stock_change_pct=-1)) is None

def test_rubber_tire_op_down_stock_up_negative():
    r = rules.rule_rubber_tire_op_down_stock_up(_snap(
        china_semi_steel_op_rate_change_pct=-1,
        china_full_steel_op_rate_change_pct=-1,
        qingdao_bonded_stock_change_pct=2))
    assert r and r.score_delta == -15

def test_rubber_tire_op_normal_no_trigger():
    assert rules.rule_rubber_tire_op_down_stock_up(_snap(
        china_semi_steel_op_rate_change_pct=1,
        china_full_steel_op_rate_change_pct=1,
        qingdao_bonded_stock_change_pct=-1)) is None

def test_rubber_money_flow_flag_triggers():
    r = rules.rule_rubber_futures_money_flow_flag(_snap(nr_futures_up_but_spot_flat=True))
    assert r and r.score_delta == 0 and r.flag is not None

def test_rubber_money_flow_false_no_trigger():
    assert rules.rule_rubber_futures_money_flow_flag(
        _snap(nr_futures_up_but_spot_flat=False)) is None
