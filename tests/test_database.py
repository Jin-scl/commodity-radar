"""Database 查询语义单测。

覆盖：
- seed 数据被默认排除
- as_of_date 真实按日期回放
- save_event 接收 timestamp
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.storage.database import Database


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        yield Database(Path(tmp) / "test.db")


def _ind(name, value, timestamp, source="manual", commodity="sugar"):
    return {
        "commodity": commodity, "name": name,
        "value_num": value, "value_text": None,
        "unit": "x", "source": source,
        "timestamp": timestamp, "fetched_at": "2026-06-01T00:00:00",
        "confidence": "high", "is_manual": False, "notes": None,
    }


def test_seed_indicators_excluded_by_default(db):
    """seed 数据应该不影响 get_latest_indicators 默认返回。"""
    # 真实 manual：2026-04-30 观测
    db.save_indicator(_ind("mpob_stock", 1.95, "2026-04-30", source="manual"))
    # seed：2026-05-30 扰动值
    db.save_indicator(_ind("mpob_stock", 1.50, "2026-05-30", source="seed"))

    latest = db.get_latest_indicators(commodity="sugar", names=["mpob_stock"])
    assert len(latest) == 1
    assert latest[0]["value_num"] == 1.95
    assert latest[0]["source"] == "manual"
    assert latest[0]["timestamp"] == "2026-04-30"


def test_include_seed_returns_seeded(db):
    db.save_indicator(_ind("mpob_stock", 1.95, "2026-04-30", source="manual"))
    db.save_indicator(_ind("mpob_stock", 1.50, "2026-05-30", source="seed"))

    latest = db.get_latest_indicators(commodity="sugar", names=["mpob_stock"],
                                       include_seed=True)
    assert len(latest) == 1
    # seed 时间戳更新，应该胜出
    assert latest[0]["source"] == "seed"
    assert latest[0]["timestamp"] == "2026-05-30"


def test_as_of_date_filters_future_data(db):
    """as_of_date 应该排除未来时间戳的数据，实现"按日期回放"。"""
    db.save_indicator(_ind("brent", 80.0, "2026-05-28"))
    db.save_indicator(_ind("brent", 90.0, "2026-05-30"))
    db.save_indicator(_ind("brent", 100.0, "2026-06-01"))

    # 看 2026-05-29 那天的快照 → 应该返回 80
    snap_29 = db.get_latest_indicators(names=["brent"], as_of_date="2026-05-29")
    assert len(snap_29) == 1
    assert snap_29[0]["value_num"] == 80.0

    # 看 2026-05-30 那天 → 应该返回 90
    snap_30 = db.get_latest_indicators(names=["brent"], as_of_date="2026-05-30")
    assert snap_30[0]["value_num"] == 90.0

    # 不指定 → 返回最新 100
    snap_latest = db.get_latest_indicators(names=["brent"])
    assert snap_latest[0]["value_num"] == 100.0


def test_save_event_with_custom_timestamp(db):
    db.save_event("palm", "policy", "B50 announced",
                  severity="critical", timestamp="2026-05-15")
    recent = db.get_recent_events(hours=24 * 365)  # 一年内
    assert len(recent) == 1
    assert recent[0]["timestamp"] == "2026-05-15"
    assert recent[0]["message"] == "B50 announced"


def test_save_event_default_timestamp(db):
    db.save_event("palm", "policy", "event without ts")
    recent = db.get_recent_events(hours=24)
    assert len(recent) == 1
    # 默认时间戳应该是 ISO 格式（带 T 或 +）
    assert ("T" in recent[0]["timestamp"]) or ("-" in recent[0]["timestamp"])
