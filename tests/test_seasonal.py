"""季节性基准单测：vs 5 年同月/同周均值。"""
from __future__ import annotations

from src.indicators import rules


def _s(**kwargs):
    return {k: {"value": v} for k, v in kwargs.items()}


def test_seasonal_deviation_helper():
    snap = _s(actual=180, avg=200)
    assert rules._seasonal_deviation_pct(snap, "actual", "avg") == -10.0
    snap = _s(actual=220, avg=200)
    assert rules._seasonal_deviation_pct(snap, "actual", "avg") == 10.0
    assert rules._seasonal_deviation_pct(_s(actual=180), "actual", "avg") is None


# ---------- 棕榈油 ----------
def test_palm_stock_below_seasonal_bullish():
    snap = _s(mpob_end_stock_mt=1.60, mpob_end_stock_5y_avg_mt=1.85)
    r = rules.rule_palm_mpob_stock_vs_seasonal(snap)
    assert r and r.score_delta == 8 and r.side == "bullish"


def test_palm_stock_above_seasonal_bearish():
    snap = _s(mpob_end_stock_mt=2.20, mpob_end_stock_5y_avg_mt=1.85)
    r = rules.rule_palm_mpob_stock_vs_seasonal(snap)
    assert r and r.score_delta == -8


def test_palm_stock_seasonal_in_range_no_trigger():
    snap = _s(mpob_end_stock_mt=1.90, mpob_end_stock_5y_avg_mt=1.85)
    assert rules.rule_palm_mpob_stock_vs_seasonal(snap) is None


def test_palm_export_above_seasonal():
    snap = _s(mpob_export_mt=1.40, mpob_export_5y_avg_mt=1.20)
    r = rules.rule_palm_mpob_export_vs_seasonal(snap)
    assert r and r.score_delta == 6


def test_palm_export_below_seasonal():
    snap = _s(mpob_export_mt=1.05, mpob_export_5y_avg_mt=1.20)
    r = rules.rule_palm_mpob_export_vs_seasonal(snap)
    assert r and r.score_delta == -5


def test_palm_demand_vs_seasonal_above():
    snap = _s(india_palm_import_mt=0.70, india_palm_import_5y_avg_mt=0.60,
              china_palm_import_mt=0.50, china_palm_import_5y_avg_mt=0.42)
    r = rules.rule_palm_demand_vs_seasonal(snap)
    # total = 1.20, avg = 1.02, dev = +17.6%
    assert r and r.score_delta == 6


def test_palm_demand_vs_seasonal_below():
    snap = _s(india_palm_import_mt=0.45, india_palm_import_5y_avg_mt=0.60,
              china_palm_import_mt=0.35, china_palm_import_5y_avg_mt=0.42)
    r = rules.rule_palm_demand_vs_seasonal(snap)
    # total = 0.80, avg = 1.02, dev = -21.6%
    assert r and r.score_delta == -6


def test_palm_demand_seasonal_missing_data():
    assert rules.rule_palm_demand_vs_seasonal(_s()) is None


# ---------- 橡胶 ----------
def test_rubber_qingdao_below_seasonal_bullish():
    snap = _s(qingdao_bonded_stock_kt=150.0,
              qingdao_bonded_stock_5y_avg_kt=180.0)
    r = rules.rule_rubber_qingdao_vs_seasonal(snap)
    # dev = -16.7%
    assert r and r.score_delta == 6


def test_rubber_qingdao_above_seasonal_bearish():
    snap = _s(qingdao_bonded_stock_kt=220.0,
              qingdao_bonded_stock_5y_avg_kt=180.0)
    r = rules.rule_rubber_qingdao_vs_seasonal(snap)
    # dev = +22.2%
    assert r and r.score_delta == -6


def test_rubber_qingdao_seasonal_no_trigger():
    snap = _s(qingdao_bonded_stock_kt=185.0,
              qingdao_bonded_stock_5y_avg_kt=180.0)
    assert rules.rule_rubber_qingdao_vs_seasonal(snap) is None


def test_rubber_tire_op_above_seasonal():
    snap = _s(china_semi_steel_tire_operating_rate_pct=75.0,
              china_semi_steel_tire_op_rate_5y_avg_pct=68.0,
              china_full_steel_tire_operating_rate_pct=60.0,
              china_full_steel_tire_op_rate_5y_avg_pct=55.0)
    r = rules.rule_rubber_tire_op_vs_seasonal(snap)
    # dev_semi=7, dev_full=5, avg=6 → +6 触发
    assert r and r.score_delta == 6


def test_rubber_tire_op_below_seasonal():
    snap = _s(china_semi_steel_tire_operating_rate_pct=60.0,
              china_semi_steel_tire_op_rate_5y_avg_pct=68.0,
              china_full_steel_tire_operating_rate_pct=50.0,
              china_full_steel_tire_op_rate_5y_avg_pct=55.0)
    r = rules.rule_rubber_tire_op_vs_seasonal(snap)
    # dev = -6.5 → < -3 → bearish
    assert r and r.score_delta == -6


def test_rubber_tire_op_seasonal_in_range():
    snap = _s(china_semi_steel_tire_operating_rate_pct=70.0,
              china_semi_steel_tire_op_rate_5y_avg_pct=68.0,
              china_full_steel_tire_operating_rate_pct=56.0,
              china_full_steel_tire_op_rate_5y_avg_pct=55.0)
    # dev = 1.5 → no trigger
    assert rules.rule_rubber_tire_op_vs_seasonal(snap) is None
