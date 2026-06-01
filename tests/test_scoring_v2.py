"""评分体系 v2 升级单测：置信度衰减 / category 封顶 / 等级穿越 / 因子 diff。"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.indicators.scoring import (
    CATEGORY_CAP, CONFIDENCE_MULT, _overall_confidence,
    evaluate_commodity,
)
from src.storage.database import Database
from src.utils import load_config


CFG = load_config()


def _entry(value, confidence="high"):
    return {"value": value, "confidence": confidence, "is_manual": False}


def test_high_confidence_no_decay():
    """high confidence → delta 不衰减。"""
    snap = {
        "nino34": _entry(0.6, "high"),  # 触发 +5
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    # +5 with 1.0 mult
    assert r["final_score"] == 5
    assert r["triggered_count"] == 1


def test_low_confidence_decay():
    """low confidence → delta * 0.4。"""
    snap = {
        "nino34": _entry(0.6, "low"),  # 原 +5, 衰减后 round(5*0.4)=2
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    assert r["final_score"] == 2


def test_medium_confidence_decay():
    snap = {
        "nino34": _entry(1.2, "medium"),  # 原 +10, 衰减 0.8 → 8
    }
    r = evaluate_commodity("sugar", snap, db=None, config=CFG)
    assert r["final_score"] == 8


def test_category_cap_prevents_double_count():
    """单 category 贡献被 CATEGORY_CAP 限制。
    构造 4 条同类规则总贡献 +35（>25），应被 cap 到 25。
    """
    # malaysia 类规则：stock_lt_160 (+15), production_below_seasonal (+8),
    # export_up_stock_down (+10) → 总 +33，cap 后 25
    snap = {
        "mpob_end_stock_mt": _entry(1.55, "high"),  # +15
        "mpob_cpo_production_mt": _entry(1.5, "high"),  # 与下面配合 +8
        "mpob_cpo_production_5y_avg_mt": _entry(1.7, "high"),
        "mpob_export_mom_change_pct": _entry(5, "high"),  # 与下面配合 +10
        "mpob_stock_mom_change_pct": _entry(-3, "high"),
    }
    r = evaluate_commodity("palm", snap, db=None, config=CFG)
    # 三条规则原始总和 +33，cap 到 +25
    assert r["category_breakdown"]["malaysia"] == CATEGORY_CAP
    # raw_score 应该等于 category_capped 之和（不含 raw 的原始 33）
    # confidence 全 high，所以 cap 前应该是 15+8+10=33；cap 后 25
    assert r["raw_score"] == 25


def test_overall_confidence_average():
    snap = {
        "a": _entry(1, "high"),
        "b": _entry(2, "high"),
        "c": _entry(3, "low"),
    }
    score = _overall_confidence(snap)
    # 2 high (100) + 1 low (30) = 230/3 = 76.67 → 76
    assert 75 <= score <= 78


def test_regime_change_detected():
    """昨日绿色 25 分 → 今日黄色 35 分，应检测到等级穿越。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        # 写昨日 score 25 (green)
        db.save_score({
            "commodity": "sugar", "score_date": "2026-05-31",
            "raw_score": 25, "final_score": 25,
            "risk_level": "green", "risk_level_label": "绿色",
            "score_change_1d": None, "score_change_7d": None,
            "confidence_score": 80,
        })
        # 今日触发更多规则达到 黄色阈值
        snap = {
            "nino34": _entry(1.2, "high"),       # +10
            "india_monsoon_below_normal_weeks": _entry(2, "high"),  # +5
            "maharashtra_rainfall_anomaly_pct": _entry(-25, "high"),  # +10
            "brazil_cs_crush_yoy_pct": _entry(-3.0, "high"),  # +5
            "brazil_sugar_mix_change_pp": _entry(-2.5, "high"),  # +10
        }
        r = evaluate_commodity("sugar", snap, db=db, score_date="2026-06-01",
                                config=CFG)
        # final 应该 >= 31 (黄色)
        assert r["final_score"] >= 31
        assert r["risk_level"] == "yellow"
        assert r["regime_change"] is not None
        assert r["regime_change"]["from"] == "绿色"
        assert r["regime_change"]["to"] == "黄色"
        assert r["regime_change"]["direction"] == "up"


def test_factor_diff_added_removed():
    """昨日触发 [A, B]，今日触发 [B, C] → added=[C], removed=[A], persistent=[B]。"""
    import json
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        db.save_score({
            "commodity": "sugar", "score_date": "2026-05-31",
            "raw_score": 10, "final_score": 10,
            "risk_level": "green", "risk_level_label": "绿色",
            "triggered_rules_json": json.dumps([
                "enso.nino34.gt_0_5",
                "sugar.india.maha_kar_dry",
            ]),
        })
        # 今日：消失 maha_kar_dry，新增 brazil 规则
        snap = {
            "nino34": _entry(0.6, "high"),  # 持续 enso.nino34.gt_0_5
            "brazil_cs_crush_yoy_pct": _entry(-3.0, "high"),  # 新增
        }
        r = evaluate_commodity("sugar", snap, db=db, score_date="2026-06-01",
                                config=CFG)
        diff = r["factor_diff"]
        assert "enso.nino34.gt_0_5" in diff["persistent"]
        assert "sugar.india.maha_kar_dry" in diff["removed"]
        assert "sugar.brazil.crush_yoy_down" in diff["added"]
