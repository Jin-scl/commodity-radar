"""评分聚合层 —— 输入 snapshot dict，输出 0-100 final_score + 等级 + 变化 + 因子。"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from src.indicators.rules import RULES_BY_COMMODITY, RuleResult
from src.utils import load_config
from src.storage.database import Database, today_str


def _classify(score: int, levels: list[dict]) -> tuple[str, str, str]:
    for lvl in levels:
        if lvl["min"] <= score <= lvl["max"]:
            return lvl["level"], lvl["label"], lvl.get("desc", "")
    return "unknown", "未知", ""


def _conclude(score: int, change_1d: Optional[int],
              change_7d: Optional[int]) -> str:
    """生成中性结论文字（绝不出现买卖）。"""
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
    return "；".join(parts) or "中性，需要继续验证"


def evaluate_commodity(commodity: str, snapshot: dict,
                       db: Optional[Database] = None,
                       score_date: Optional[str] = None,
                       config: Optional[dict] = None) -> dict:
    """对单一品种计算评分结果。
    snapshot: {indicator_name: {value, unit, ...}} (扁平结构)
    """
    cfg = config or load_config()
    score_date = score_date or today_str()
    rules = RULES_BY_COMMODITY.get(commodity, [])
    triggered: list[RuleResult] = []

    for rule_fn in rules:
        try:
            res = rule_fn(snapshot)
        except Exception as e:  # rule 错误不影响其它规则
            res = None
            print(f"[rule error] {commodity} {rule_fn.__name__}: {e}")
        if res is not None:
            triggered.append(res)

    raw_score = sum(r.score_delta for r in triggered)
    final_score = max(0, min(100, raw_score))
    level, label, _ = _classify(final_score, cfg["risk_levels"])

    bullish = [asdict(r) for r in triggered if r.side == "bullish"]
    bearish = [asdict(r) for r in triggered if r.side == "bearish"]
    flags = [asdict(r) for r in triggered if r.flag]

    # 历史对比
    change_1d = None
    change_7d = None
    if db is not None:
        prev1 = db.get_score_n_days_ago(commodity, 1, score_date)
        prev7 = db.get_score_n_days_ago(commodity, 7, score_date)
        if prev1:
            change_1d = final_score - int(prev1["final_score"])
        if prev7:
            change_7d = final_score - int(prev7["final_score"])

    conclusion = _conclude(final_score, change_1d, change_7d)

    # 按 category 汇总贡献度（仅用于报告展示）
    category_breakdown: dict[str, int] = {}
    for r in triggered:
        category_breakdown[r.category] = (
            category_breakdown.get(r.category, 0) + r.score_delta
        )

    return {
        "commodity": commodity,
        "score_date": score_date,
        "raw_score": raw_score,
        "final_score": final_score,
        "risk_level": level,
        "risk_level_label": label,
        "score_change_1d": change_1d,
        "score_change_7d": change_7d,
        "bullish_factors": bullish,
        "bearish_factors": bearish,
        "neutral_flags": flags,
        "triggered_count": len(triggered),
        "category_breakdown": category_breakdown,
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
            "score_change_1d": r.get("score_change_1d"),
            "score_change_7d": r.get("score_change_7d"),
            "bullish_json": r.get("bullish_factors", []),
            "bearish_json": r.get("bearish_factors", []),
            "triggered_alerts_json": alerts.get(commodity, []),
            "payload_json": {
                "conclusion": r["conclusion"],
                "category_breakdown": r["category_breakdown"],
                "neutral_flags": r.get("neutral_flags", []),
                "triggered_count": r["triggered_count"],
            },
        })
