"""价格确认模块单测：confirmed / partial / weak / diverging / no_data / neutral。"""
from __future__ import annotations

from src.indicators.scoring import _compute_price_confirmation
from src.utils import load_config


CFG = load_config()


def _e(value, confidence="high"):
    return {"value": value, "confidence": confidence}


# ---------- sugar ----------
def test_sugar_confirmed_when_all_prices_up():
    """ICE/伦敦白糖同步上涨 + USD/BRL 下跌（雷亚尔升值，巴西出口竞争力削弱）
    → 价格强确认基本面偏多。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(2.0),
        "london_white_sugar_change_pct_5d": _e(1.5),
        "usd_brl_change_pct_5d": _e(-1.0),  # invert → +1.0
    }
    pc = _compute_price_confirmation("sugar", final_score=55, snapshot=snap)
    assert pc["status"] == "confirmed"
    assert pc["weighted_pct"] == 100


def test_sugar_diverging_when_prices_drop():
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(-2.0),
        "london_white_sugar_change_pct_5d": _e(-1.5),
        "usd_brl_change_pct_5d": _e(1.0),  # invert → -1.0
    }
    pc = _compute_price_confirmation("sugar", final_score=55, snapshot=snap)
    assert pc["status"] == "diverging"
    assert pc["weighted_pct"] == -100


def test_sugar_price_leading_when_fundamental_low_but_price_strong():
    """v3：基本面绿但价格强烈偏多 → price_leading（不再误标 neutral）。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(2.0),
        "london_white_sugar_change_pct_5d": _e(1.5),
        "usd_brl_change_pct_5d": _e(-1.0),
    }
    pc = _compute_price_confirmation("sugar", final_score=20, snapshot=snap)
    assert pc["status"] == "price_leading"
    assert "价格领先偏多" in pc["message"]


def test_sugar_neutral_when_all_flat():
    """基本面绿 + 价格中性 → neutral。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(0.1),
        "london_white_sugar_change_pct_5d": _e(0.0),
        "usd_brl_change_pct_5d": _e(0.0),
    }
    pc = _compute_price_confirmation("sugar", final_score=20, snapshot=snap)
    assert pc["status"] == "neutral"


def test_sugar_no_data_when_signals_missing():
    pc = _compute_price_confirmation("sugar", final_score=55, snapshot={})
    assert pc["status"] == "no_data"


# ---------- palm ----------
def test_palm_partial_when_mixed_signals():
    """BMD 涨但价差走平、利润转负 → partial。"""
    snap = {
        "bmd_palm_oil_change_pct_5d": _e(1.5),         # up (+2.0)
        "bmd_calendar_spread_change_5d": _e(2),         # flat
        "biodiesel_margin_usd": _e(-10),                # down (-0.8)
    }
    pc = _compute_price_confirmation("palm", final_score=55, snapshot=snap)
    assert pc["status"] in ("partial", "weak")
    # weighted = 2.0 - 0.8 = 1.2; total = 3.8 → pct = 0.32 → partial
    assert pc["weighted_pct"] > 0


def test_palm_confirmed():
    snap = {
        "bmd_palm_oil_change_pct_5d": _e(2.0),
        "bmd_calendar_spread_change_5d": _e(10),
        "biodiesel_margin_usd": _e(80),
    }
    pc = _compute_price_confirmation("palm", final_score=55, snapshot=snap)
    assert pc["status"] == "confirmed"


# ---------- rubber ----------
def test_rubber_diverging_strong():
    """期货跌 + 现货贴水扩大 → 全部 down → diverging。"""
    snap = {
        "shfe_ru_change_pct_5d": _e(-1.5),
        "ine_nr20_change_pct_5d": _e(-2.0),
        "spot_premium_discount_yuan": _e(-200),  # < -50 → down
    }
    pc = _compute_price_confirmation("rubber", final_score=55, snapshot=snap)
    assert pc["status"] == "diverging"


def test_rubber_weak_when_mostly_flat():
    snap = {
        "shfe_ru_change_pct_5d": _e(0.2),           # flat
        "ine_nr20_change_pct_5d": _e(-0.3),          # flat
        "spot_premium_discount_yuan": _e(-100),      # down
    }
    pc = _compute_price_confirmation("rubber", final_score=55, snapshot=snap)
    # 2 flat + 1 down → weighted < 0, weak/diverging
    assert pc["status"] in ("weak", "diverging")


# ---------- 端到端：evaluate_commodity 输出含 price_confirmation ----------
def test_evaluate_commodity_includes_price_confirmation():
    from src.indicators.scoring import evaluate_commodity
    # 触发足够分数让 final >= 31
    snap = {
        "nino34": _e(1.2),                              # +10
        "india_monsoon_below_normal_weeks": _e(2),       # +5
        "maharashtra_rainfall_anomaly_pct": _e(-25),     # +10
        "brazil_sugar_mix_change_pp": _e(-2.5),          # +10
        # 价格信号
        "ice_raw_sugar_change_pct_5d": _e(2.0),
        "london_white_sugar_change_pct_5d": _e(1.5),
        "usd_brl_change_pct_5d": _e(-1.0),
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    assert r["price_confirmation"]["status"] == "confirmed"
    # conclusion 文字应该融入价格确认
    assert "价格" in r["conclusion"]


def test_evaluate_commodity_price_leading_when_fundamental_zero():
    """v3：score=0 + 价格强偏多 → price_leading 仍出现在 conclusion。"""
    from src.indicators.scoring import evaluate_commodity
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(2.0),
        "london_white_sugar_change_pct_5d": _e(1.5),
        "usd_brl_change_pct_5d": _e(-1.0),
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    assert r["final_score"] == 0
    assert r["price_confirmation"]["status"] == "price_leading"
    # conclusion 应包含价格先行文字
    assert "价格领先" in r["conclusion"]
