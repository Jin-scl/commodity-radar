"""预期差模块单测：vs 市场预期的 surprise %。"""
from __future__ import annotations

from src.indicators import rules


def _s(**kwargs):
    return {k: {"value": v} for k, v in kwargs.items()}


# ---------- 通用 helper ----------
def test_surprise_pct_below_expected():
    snap = _s(actual=180, expected=200)
    pct = rules._surprise_pct(snap, "actual", "expected")
    assert pct == -10.0


def test_surprise_pct_above_expected():
    snap = _s(actual=220, expected=200)
    pct = rules._surprise_pct(snap, "actual", "expected")
    assert pct == 10.0


def test_surprise_pct_missing_data():
    assert rules._surprise_pct(_s(actual=180), "actual", "expected") is None
    assert rules._surprise_pct(_s(expected=200), "actual", "expected") is None


# ---------- MPOB 库存预期差 ----------
def test_palm_stock_below_expected_bullish():
    snap = _s(mpob_end_stock_mt=1.85, mpob_end_stock_mt_expected=2.05)
    r = rules.rule_palm_mpob_stock_vs_expected(snap)
    assert r and r.score_delta == 12 and r.side == "bullish"


def test_palm_stock_above_expected_bearish():
    snap = _s(mpob_end_stock_mt=2.20, mpob_end_stock_mt_expected=2.05)
    r = rules.rule_palm_mpob_stock_vs_expected(snap)
    assert r and r.score_delta == -10 and r.side == "bearish"


def test_palm_stock_in_line_no_trigger():
    """预期 ±5% 之内不触发。"""
    snap = _s(mpob_end_stock_mt=2.00, mpob_end_stock_mt_expected=2.05)
    assert rules.rule_palm_mpob_stock_vs_expected(snap) is None


# ---------- MPOB 产量预期差 ----------
def test_palm_prod_below_expected():
    snap = _s(mpob_cpo_production_mt=1.55, mpob_cpo_production_mt_expected=1.70)
    r = rules.rule_palm_mpob_prod_vs_expected(snap)
    assert r and r.score_delta == 10 and r.side == "bullish"


def test_palm_prod_above_expected():
    snap = _s(mpob_cpo_production_mt=1.85, mpob_cpo_production_mt_expected=1.70)
    r = rules.rule_palm_mpob_prod_vs_expected(snap)
    assert r and r.score_delta == -8


# ---------- MPOB 出口预期差（方向反转：出口高 = 利多）----------
def test_palm_export_above_expected_bullish():
    snap = _s(mpob_export_mt=1.40, mpob_export_mt_expected=1.25)
    r = rules.rule_palm_mpob_export_vs_expected(snap)
    assert r and r.score_delta == 8 and r.side == "bullish"


def test_palm_export_below_expected_bearish():
    snap = _s(mpob_export_mt=1.10, mpob_export_mt_expected=1.25)
    r = rules.rule_palm_mpob_export_vs_expected(snap)
    assert r and r.score_delta == -6


# ---------- 白糖产量预期差 ----------
def test_sugar_india_below_expected():
    snap = _s(india_sugar_production_mt=30.0,
              india_sugar_production_mt_expected=32.0)
    r = rules.rule_sugar_india_prod_vs_expected(snap)
    assert r and r.score_delta == 12 and "印度" in r.label


def test_sugar_india_above_expected():
    snap = _s(india_sugar_production_mt=34.0,
              india_sugar_production_mt_expected=32.0)
    r = rules.rule_sugar_india_prod_vs_expected(snap)
    assert r and r.score_delta == -8


def test_sugar_thai_below_expected():
    snap = _s(thailand_sugar_production_mt=8.8,
              thailand_sugar_production_mt_expected=9.5)
    r = rules.rule_sugar_thai_prod_vs_expected(snap)
    assert r and r.score_delta == 10


def test_sugar_brazil_above_expected():
    snap = _s(brazil_sugar_production_mt=43.0,
              brazil_sugar_production_mt_expected=40.0)
    r = rules.rule_sugar_brazil_prod_vs_expected(snap)
    assert r and r.score_delta == -6


# ---------- 边界 ----------
def test_no_expected_returns_none():
    snap = _s(india_sugar_production_mt=30.0)
    assert rules.rule_sugar_india_prod_vs_expected(snap) is None
