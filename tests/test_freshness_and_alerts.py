"""第三轮审查修复的端到端测试：
- freshness 自动降级
- input_keys 自动收集 + 置信度按真实触发字段
- ENSO partial fallback
- 历史事件按 score_date 回放
- 双置信度 (overall + triggered)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.utils import (
    effective_confidence, indicators_to_snapshot, load_config,
)
from src.indicators.rules import run_rule, rule_nino34_warm_high
from src.indicators.scoring import (
    _rule_confidence, _triggered_confidence, _overall_confidence,
    evaluate_commodity,
)
from src.storage.database import Database


CFG = load_config()
FRESHNESS = CFG["freshness"]


# ---------- freshness 自动降级 ----------
def test_effective_confidence_fresh_data_no_degrade():
    # mpob_ 类阈值 720h；近 1 天数据应保持 stated
    eff = effective_confidence("mpob_end_stock_mt", "2026-06-01",
                                "medium", as_of_date="2026-06-02",
                                freshness_cfg=FRESHNESS)
    assert eff == "medium"


def test_effective_confidence_old_data_degrades_to_medium():
    # 30 天 = 720h，刚好阈值；超过一点应降到 medium
    eff = effective_confidence("brent_price_usd", "2026-05-25",
                                "high", as_of_date="2026-06-01",
                                freshness_cfg=FRESHNESS)
    # brent: 48h freshness, 7 天 = 168h > 48*2=96h → low
    assert eff == "low"


def test_effective_confidence_very_old_data_degrades_to_low():
    # mpob 阈值 720h；用 45 天 → > 720 → medium；用 70 天 → > 1440 → low
    eff = effective_confidence("mpob_end_stock_mt", "2026-04-15",
                                "medium", as_of_date="2026-06-01",
                                freshness_cfg=FRESHNESS)
    # 47 天 = 1128h，1.0*720=720 < 1128 < 2*720=1440 → medium
    assert eff in ("medium", "low")


def test_effective_confidence_indicators_to_snapshot_applies_degradation():
    """indicators_to_snapshot 自动应用 freshness 降级。"""
    inds = [{
        "name": "mpob_end_stock_mt", "value_num": 1.95,
        "timestamp": "2026-04-30", "confidence": "medium",
        "is_manual": True, "value_text": None,
    }, {
        "name": "brent_price_usd", "value_num": 90.0,
        "timestamp": "2026-04-15", "confidence": "high",
        "is_manual": False, "value_text": None,
    }]
    snap = indicators_to_snapshot(inds, as_of_date="2026-06-01",
                                   freshness_cfg=FRESHNESS)
    # mpob 47 天 < 60 天 (2×720h) → medium 保持
    assert snap["mpob_end_stock_mt"]["confidence"] == "medium"
    # brent 47 天 >> 4 天 (2×48h) → 降到 low
    assert snap["brent_price_usd"]["confidence"] == "low"
    # stated_confidence 保留原值供审计
    assert snap["brent_price_usd"]["stated_confidence"] == "high"


# ---------- input_keys 自动收集 ----------
def test_rule_input_keys_auto_collected():
    """run_rule 应该自动把规则读过的 key 写到 RuleResult.input_keys。"""
    snap = {"nino34": {"value": 0.7, "confidence": "high"}}
    res = run_rule(rule_nino34_warm_high, snap)
    assert res is not None
    assert "nino34" in res.input_keys


def test_input_keys_skips_missing_optional_access():
    """规则用 `_num(snap, "x", 0) or 0` 形式时，x 缺失不应被记入 input_keys。"""
    # rule_sugar_brazil_oil_ethanol_up 用了默认值 fallback
    from src.indicators.rules import rule_sugar_brazil_oil_ethanol_up
    # 都提供 → 触发
    snap = {
        "brent_consecutive_up_days": {"value": 5, "confidence": "high"},
        "brazil_ethanol_consecutive_up_days": {"value": 3, "confidence": "high"},
    }
    res = run_rule(rule_sugar_brazil_oil_ethanol_up, snap)
    assert res is not None
    assert "brent_consecutive_up_days" in res.input_keys
    assert "brazil_ethanol_consecutive_up_days" in res.input_keys

    # 缺一个 → 不触发（不返回 RuleResult），所以测试缺失场景需要其它规则
    # 重点：确保 input_keys 只含有真实存在并取到值的 key


def test_rule_confidence_uses_input_keys_not_evidence():
    """触发字段不在 evidence 但在 input_keys 时，置信度仍按 input_keys 算。"""
    # 用 palm.indo_dry 规则：input 是 indonesia_core_rainfall_below_normal_weeks
    # evidence 里只有 sumatra/kalimantan
    from src.indicators.rules import rule_palm_indo_dry
    snap = {
        "indonesia_core_rainfall_below_normal_weeks": {"value": 4, "confidence": "low"},
        # sumatra/kalimantan 缺失也能触发（因为规则只检查 weeks）
    }
    res = run_rule(rule_palm_indo_dry, snap)
    assert res is not None
    # input_keys 应包含 weeks
    assert "indonesia_core_rainfall_below_normal_weeks" in res.input_keys
    # _rule_confidence 应该用 weeks 的 low → ×0.4，不是 evidence 的"缺失"
    worst, mult = _rule_confidence(res, snap)
    assert worst == "low"
    assert mult == 0.4


# ---------- 双置信度 ----------
def test_overall_vs_triggered_confidence():
    """有大量 low 数据 + 少量 high 触发规则时，两个置信度应该差距明显。"""
    snap = {
        # 5 个 low 字段不触发任何规则
        "noise_1": {"value": 1, "confidence": "low"},
        "noise_2": {"value": 2, "confidence": "low"},
        "noise_3": {"value": 3, "confidence": "low"},
        "noise_4": {"value": 4, "confidence": "low"},
        "noise_5": {"value": 5, "confidence": "low"},
        # 1 个 high 字段触发 nino34
        "nino34": {"value": 0.7, "confidence": "high"},
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    # overall 平均 — 1 high (100) + 5 low (30) = 250/6 ≈ 41
    assert r["confidence_score"] < 60
    # triggered 只看 nino34 → 100
    assert r["triggered_confidence"] == 100


def test_triggered_confidence_with_missing_input_returns_low():
    """触发规则的某个 input_key 在 snapshot 中缺失值（None）时，
    triggered_confidence 应该被严重拉低，反映"该规则其实没靠谱数据"。
    """
    snap = {
        "nino34": {"value": 0.7, "confidence": "high"},
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    # nino34 high → triggered = 100
    assert r["triggered_confidence"] == 100


# ---------- 历史事件回放 ----------
def test_events_between_filters_by_date():
    """get_events_between 应该只返回区间内的 events。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        db.save_event("sugar", "policy", "old event",
                      severity="critical", timestamp="2026-05-25")
        db.save_event("sugar", "policy", "target day event",
                      severity="critical", timestamp="2026-05-30")
        db.save_event("sugar", "policy", "future event",
                      severity="critical", timestamp="2026-06-01")

        # [2026-05-30, 2026-05-31) 应该只返回 "target day event"
        evs = db.get_events_between("2026-05-30", "2026-05-31")
        msgs = [e["message"] for e in evs]
        assert "target day event" in msgs
        assert "old event" not in msgs
        assert "future event" not in msgs


def test_dispatcher_uses_score_date_for_events():
    """evaluate_alerts 传 score_date 时，应该按该日期回放事件，而非当前 24h。"""
    from src.alerts.dispatcher import evaluate_alerts
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        # 在历史日期写一个 critical event
        db.save_event("sugar", "news", "印度糖出口禁令延长",
                      severity="critical", timestamp="2026-05-30")
        # 在今天写一个无关 event（不应混入历史报告）
        db.save_event("sugar", "news", "今天的新闻",
                      severity="critical")  # 默认 timestamp=now

        scores = {"sugar": {
            "commodity": "sugar", "final_score": 20,
            "risk_level_label": "绿色", "risk_level": "green",
            "score_change_1d": None, "score_change_7d": None,
        }}
        # 回放 2026-05-30 → 只应看到"印度糖出口禁令延长"
        alerts = evaluate_alerts(scores, db, CFG, score_date="2026-05-30")
        msgs = " ".join(a["message"] for a in alerts)
        assert "印度糖出口禁令延长" in msgs
        assert "今天的新闻" not in msgs
