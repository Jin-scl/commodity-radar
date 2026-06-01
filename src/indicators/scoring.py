"""评分聚合层 —— 输入 snapshot dict，输出 0-100 final_score + 等级 + 变化 + 因子。"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from src.indicators.rules import RULES_BY_COMMODITY, RuleResult
from src.utils import get_logger, load_config
from src.storage.database import Database, today_str

logger = get_logger()


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


# 数据置信度衰减系数（low 数据不应该和 high 数据等权贡献分数）
CONFIDENCE_MULT = {"high": 1.0, "medium": 0.8, "low": 0.4}

# 单 category 贡献上限（避免重复计分把同一风险叠加过多）
CATEGORY_CAP = 25


def _rule_confidence(rule_res: "RuleResult", snapshot: dict) -> tuple[str, float]:
    """规则触发时，evidence 中所有 indicator 的 confidence 取最低；
    返回 (worst_confidence, multiplier)。"""
    confs: list[str] = []
    for ind_name in rule_res.evidence.keys():
        entry = snapshot.get(ind_name)
        if entry:
            confs.append(entry.get("confidence") or "medium")
    if not confs:
        return "high", 1.0
    # high < medium < low（按系数）
    worst = min(confs, key=lambda c: CONFIDENCE_MULT.get(c, 0.6))
    return worst, CONFIDENCE_MULT.get(worst, 0.6)


def _overall_confidence(snapshot: dict) -> int:
    """所有 indicator 置信度的均值（0-100），用于报告展示。"""
    if not snapshot:
        return 0
    score_map = {"high": 100, "medium": 70, "low": 30}
    total = 0
    n = 0
    for entry in snapshot.values():
        c = (entry or {}).get("confidence") or "medium"
        total += score_map.get(c, 60)
        n += 1
    return int(total / n) if n else 0


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
            res = rule_fn(snapshot)
        except Exception as e:
            res = None
            logger.warning("[rule error] %s %s: %s",
                           commodity, rule_fn.__name__, e)
        if res is not None:
            triggered.append(res)

    # 置信度衰减（修改 RuleResult 的 score_delta，记录原值便于审计）
    for r in triggered:
        original = r.score_delta
        worst, mult = _rule_confidence(r, snapshot)
        r.score_delta = int(round(original * mult))
        # evidence 里塞一份 _confidence 记录，方便报告展示
        r.evidence["_rule_confidence"] = worst
        r.evidence["_original_delta"] = original

    # Category 聚合 + 封顶（重复计分抑制）
    category_raw: dict[str, int] = {}
    for r in triggered:
        category_raw.setdefault(r.category, 0)
        category_raw[r.category] += r.score_delta
    category_capped: dict[str, int] = {
        k: max(-CATEGORY_CAP, min(CATEGORY_CAP, v))
        for k, v in category_raw.items()
    }

    raw_score = sum(category_capped.values())
    final_score = max(0, min(100, raw_score))
    level, label, _ = _classify(final_score, cfg["risk_levels"])

    confidence_score = _overall_confidence(snapshot)

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

    conclusion = _conclude(final_score, change_1d, change_7d)

    return {
        "commodity": commodity,
        "score_date": score_date,
        "raw_score": raw_score,
        "final_score": final_score,
        "risk_level": level,
        "risk_level_label": label,
        "confidence_score": confidence_score,
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
            },
        })
