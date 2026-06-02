"""第四轮审查修复的单测：
- P1 date-only event 不被漏过
- P1 price_leading 状态
- P2 价格确认按置信度加权
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.indicators.scoring import _compute_price_confirmation
from src.storage.database import Database
from src.utils import load_config


CFG = load_config()


def _e(value, confidence="high"):
    return {"value": value, "confidence": confidence}


# ---------- P1 #1: get_recent_events 兼容 date-only ----------
def test_recent_events_picks_up_date_only_today_event():
    """manual event timestamp = 'YYYY-MM-DD'（无时分秒），
    旧实现用 ISO 字符串比较会漏掉；新实现应能找到。"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        db.save_event("palm", "policy", "B50 announced today",
                      severity="critical", timestamp=today)
        evs = db.get_recent_events(hours=24)
        msgs = [e["message"] for e in evs]
        assert "B50 announced today" in msgs, \
            f"date-only event {today} should be picked up by 24h window"


def test_recent_events_iso_format_still_works():
    """ISO 格式仍应正常工作。"""
    from datetime import datetime, timezone, timedelta
    recent_iso = (datetime.now(timezone.utc).astimezone()
                  - timedelta(hours=1)).isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        db.save_event("palm", "news", "1h ago iso event",
                      severity="critical", timestamp=recent_iso)
        evs = db.get_recent_events(hours=24)
        assert any(e["message"] == "1h ago iso event" for e in evs)


# ---------- P1 #2: price_leading 状态 ----------
def test_price_leading_when_low_score_strong_signals():
    """基本面 15 分（绿色）+ 价格全偏多 → price_leading。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(2.0),
        "london_white_sugar_change_pct_5d": _e(1.5),
        "usd_brl_change_pct_5d": _e(-1.0),
    }
    pc = _compute_price_confirmation("sugar", final_score=15, snapshot=snap,
                                      cfg=CFG)
    assert pc["status"] == "price_leading"


def test_price_leading_bearish_direction():
    """绿色 + 价格全偏空 → price_leading（偏空版）。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(-2.0),
        "london_white_sugar_change_pct_5d": _e(-1.5),
        "usd_brl_change_pct_5d": _e(1.0),
    }
    pc = _compute_price_confirmation("sugar", final_score=15, snapshot=snap,
                                      cfg=CFG)
    assert pc["status"] == "price_leading"
    assert "偏空" in pc["message"]


def test_price_watch_when_weak_signals():
    """价格有微弱方向但不强 → price_watch。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(0.8),       # up (w=2.0)
        "london_white_sugar_change_pct_5d": _e(0.1),  # flat
        "usd_brl_change_pct_5d": _e(0.2),             # flat
    }
    pc = _compute_price_confirmation("sugar", final_score=15, snapshot=snap,
                                      cfg=CFG)
    # 仅 1 个 up 信号 → pct = 2/(2+1.5+1) ≈ 0.44 → price_watch
    assert pc["status"] == "price_watch"


def test_neutral_when_all_flat_low_score():
    """价格全平 + 基本面低 → neutral。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(0.1),
        "london_white_sugar_change_pct_5d": _e(0.0),
        "usd_brl_change_pct_5d": _e(0.0),
    }
    pc = _compute_price_confirmation("sugar", final_score=15, snapshot=snap,
                                      cfg=CFG)
    assert pc["status"] == "neutral"


# ---------- P2 #3: 价格确认按置信度加权 ----------
def test_price_confirmation_low_confidence_diluted():
    """全 low confidence 数据时，加权得分应该被弱化 → 不会到 confirmed 强度。"""
    # 全 high → confirmed (pct=100)
    snap_high = {
        "ice_raw_sugar_change_pct_5d": _e(2.0, "high"),
        "london_white_sugar_change_pct_5d": _e(1.5, "high"),
        "usd_brl_change_pct_5d": _e(-1.0, "high"),
    }
    pc_high = _compute_price_confirmation("sugar", final_score=55,
                                           snapshot=snap_high, cfg=CFG)
    assert pc_high["status"] == "confirmed"
    assert pc_high["confidence_score"] == 100

    # 全 low → 信号方向不变，但 confidence_score 应该明显下降
    snap_low = {
        "ice_raw_sugar_change_pct_5d": _e(2.0, "low"),
        "london_white_sugar_change_pct_5d": _e(1.5, "low"),
        "usd_brl_change_pct_5d": _e(-1.0, "low"),
    }
    pc_low = _compute_price_confirmation("sugar", final_score=55,
                                          snapshot=snap_low, cfg=CFG)
    # 方向仍同（全 up），但报告里能看到置信度低
    assert pc_low["confidence_score"] == 30  # low=30


def test_price_confirmation_mixed_confidence_average():
    """high + medium + low 混合，置信度均值。"""
    snap = {
        "ice_raw_sugar_change_pct_5d": _e(2.0, "high"),
        "london_white_sugar_change_pct_5d": _e(1.5, "medium"),
        "usd_brl_change_pct_5d": _e(-1.0, "low"),
    }
    pc = _compute_price_confirmation("sugar", final_score=55, snapshot=snap,
                                      cfg=CFG)
    # 均值 = (100+70+30)/3 ≈ 66
    assert 60 <= pc["confidence_score"] <= 70
