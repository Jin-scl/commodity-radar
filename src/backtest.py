"""Monte Carlo 回测 —— 用 manual baseline 加噪声生成随机 snapshot，
统计规则触发率、分数分布、category 贡献，输出阈值校准建议。

**注意**：这不是"未来价格回测"（我们没有真实未来价格做 ground truth），
而是**机制性回测**：检验评分体系本身的稳定性，发现：
- 哪些规则永远不触发 → 阈值太严或字段缺失
- 哪些规则总是触发 → 阈值太松
- 分数等级分布是否符合设计预期（绿/黄/橙/红/紫 ~ 30/30/20/15/5%）
- 各 category 贡献是否平衡
"""
from __future__ import annotations

import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from src.indicators.scoring import evaluate_commodity
from src.utils import get_logger, load_config, load_manual_inputs


# 离散字段的概率分布（每次抽样按权重选）
DISCRETE_DISTRIBUTIONS = {
    "india_export_policy": [
        ("no_change", 0.50), ("open", 0.20),
        ("restriction", 0.15), ("ban_extended", 0.10), ("new_ban", 0.05),
    ],
    "indonesia_biodiesel_mandate": [
        ("B40", 0.40), ("B35", 0.30), ("B50_announced", 0.10),
        ("B50_implementing", 0.05), ("B50_postponed", 0.10),
        ("B50_cancelled", 0.05),
    ],
    "indonesia_export_policy": [
        ("no_change", 0.55), ("DMO_tightened", 0.20),
        ("export_tax_up", 0.15), ("export_restriction", 0.10),
    ],
    "china_guangxi_yunnan_weather_event": [
        ("normal", 0.70), ("drought", 0.10), ("frost", 0.05),
        ("flood", 0.10), ("severe", 0.05),
    ],
    "thailand_south_extreme_event": [
        ("normal", 0.70), ("heavy_rain", 0.15),
        ("drought", 0.10), ("flood", 0.05),
    ],
    "vietnam_tapping_status": [("normal", 0.85), ("delayed", 0.15)],
    "china_yunnan_rubber_weather": [("normal", 0.85), ("disrupted", 0.15)],
    "china_hainan_rubber_weather": [("normal", 0.85), ("disrupted", 0.15)],
    "enso_state": [
        ("Neutral", 0.40), ("El Niño Watch", 0.20),
        ("El Niño", 0.15), ("Strong El Niño", 0.05),
        ("La Niña Watch", 0.10), ("La Niña", 0.10),
    ],
}

# 布尔字段的真概率
BOOL_TRUE_PROB = {
    "up_high_temp_event": 0.10,
    "eu_summer_heat_drought_event": 0.15,
    "nr_futures_up_but_spot_flat": 0.20,
}


def _sample_discrete(name: str, baseline, rng: random.Random):
    dist = DISCRETE_DISTRIBUTIONS.get(name)
    if dist is None:
        return baseline
    values, weights = zip(*dist)
    return rng.choices(values, weights=weights, k=1)[0]


def _sample_bool(name: str, baseline, rng: random.Random):
    p = BOOL_TRUE_PROB.get(name)
    if p is None:
        return baseline
    return rng.random() < p


def _sample_value(name: str, entry, rng: random.Random,
                  noise_std: float = 0.25) -> object:
    """基于 baseline 加噪声生成单字段值。

    特殊处理：
    - bool：按 BOOL_TRUE_PROB 抽样
    - 离散字符串：按 DISCRETE_DISTRIBUTIONS 抽样
    - 整数（_days / _weeks / _months）：Poisson(lambda=baseline)，
      避免高斯噪声把"连续上涨 3 日"推到不合理范围
    - 其它数值：高斯 ±noise_std
    """
    if not isinstance(entry, dict):
        entry = {"value": entry}
    val = entry.get("value")
    if isinstance(val, bool):
        return _sample_bool(name, val, rng)
    if isinstance(val, str):
        return _sample_discrete(name, val, rng)
    if val is None:
        return None
    # 整数 + 字段名暗示离散计数 → Poisson
    is_count = (isinstance(val, int) and not isinstance(val, bool)) or \
        any(s in name for s in ("_days", "_weeks", "_months"))
    if is_count:
        lam = max(0.5, float(val))
        # 简单 Poisson 模拟（用累加指数）
        L = 2.71828 ** (-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= L:
                return k - 1
    if isinstance(val, (int, float)):
        noise = rng.gauss(0, noise_std)
        return val * (1 + noise)
    return val


def generate_random_snapshot(commodity: str, manual_inputs: dict,
                              rng: random.Random,
                              noise_std: float = 0.25) -> dict:
    """基于 manual_inputs.yaml 的 baseline 生成 1 个随机 snapshot。"""
    snap: dict[str, dict] = {}
    sources = [
        manual_inputs.get("common", {}) or {},
        manual_inputs.get("market", {}) or {},
        manual_inputs.get(commodity, {}) or {},
    ]
    for src in sources:
        for name, entry in src.items():
            sampled = _sample_value(name, entry, rng, noise_std)
            snap[name] = {
                "value": sampled,
                "confidence": "high",  # 回测假设数据齐全
                "is_manual": False,
            }
    return snap


def run_backtest(commodity: str, iterations: int = 1000,
                  noise_std: float = 0.25,
                  seed: int = 42) -> dict:
    """跑 N 次随机 snapshot，统计结果。"""
    logger = get_logger()
    rng = random.Random(seed)
    manual = load_manual_inputs()
    cfg = load_config()

    scores: list[int] = []
    levels: Counter = Counter()
    rule_triggers: Counter = Counter()
    category_deltas: dict[str, list[int]] = defaultdict(list)
    price_status: Counter = Counter()

    for i in range(iterations):
        snap = generate_random_snapshot(commodity, manual, rng, noise_std)
        try:
            r = evaluate_commodity(commodity, snap, db=None, config=cfg)
        except Exception as e:
            logger.warning("backtest iter %d failed: %s", i, e)
            continue
        scores.append(r["final_score"])
        levels[r["risk_level"]] += 1
        for rid in r.get("triggered_rules", []):
            rule_triggers[rid] += 1
        for cat, delta in r.get("category_breakdown", {}).items():
            category_deltas[cat].append(delta)
        pc = r.get("price_confirmation") or {}
        price_status[pc.get("status") or "unknown"] += 1

    return {
        "commodity": commodity,
        "iterations": len(scores),
        "noise_std": noise_std,
        "seed": seed,
        "scores": scores,
        "levels": dict(levels),
        "rule_triggers": dict(rule_triggers),
        "category_deltas": {k: v for k, v in category_deltas.items()},
        "price_status": dict(price_status),
    }


def _percentile(sorted_data: list, pct: float) -> float:
    if not sorted_data:
        return 0
    idx = int(len(sorted_data) * pct / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def analyze_and_render(results: dict) -> str:
    """生成 Markdown 回测报告 + 校准建议。"""
    n = results["iterations"]
    if n == 0:
        return f"# Backtest {results['commodity']}\n\nNo successful iterations.\n"

    scores = results["scores"]
    s_sorted = sorted(scores)
    mean = statistics.mean(scores)
    median = statistics.median(scores)
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0

    # 等级分布
    level_pct = {k: v / n * 100 for k, v in results["levels"].items()}

    # 规则触发率（按触发率降序）
    triggers = sorted(results["rule_triggers"].items(),
                      key=lambda x: -x[1])

    # 校准建议
    suggestions: list[str] = []
    for rid, count in results["rule_triggers"].items():
        rate = count / n
        if rate < 0.02:
            suggestions.append(
                f"`{rid}` 触发率 {rate*100:.1f}% — **阈值可能太严**，"
                f"考虑放宽（如把 ±5% 改为 ±3%）或检查字段是否真有数据"
            )
        elif rate > 0.7:
            suggestions.append(
                f"`{rid}` 触发率 {rate*100:.1f}% — **阈值可能太松**，"
                f"考虑收紧（如把 ±5% 改为 ±7%）以减少噪音"
            )

    # category 贡献分布
    cat_stats = []
    for cat, deltas in results["category_deltas"].items():
        if not deltas:
            continue
        cat_stats.append({
            "category": cat,
            "trigger_count": len(deltas),
            "trigger_rate": len(deltas) / n * 100,
            "mean_delta": statistics.mean(deltas),
            "max_delta": max(deltas),
            "min_delta": min(deltas),
        })
    cat_stats.sort(key=lambda x: -x["trigger_rate"])

    # 价格确认状态分布
    pc_pct = {k: v / n * 100 for k, v in results["price_status"].items()}

    # 渲染
    lines = [
        f"# Backtest Report — {results['commodity']}",
        "",
        f"**Iterations**: {n} ｜ **Noise σ**: {results['noise_std']} "
        f"｜ **Seed**: {results['seed']}",
        "",
        "## 分数分布",
        "",
        f"- Mean: **{mean:.1f}** ｜ Median: **{median:.0f}** ｜ Std: {stdev:.1f}",
        f"- P10 / P25 / P50 / P75 / P90: "
        f"{_percentile(s_sorted, 10):.0f} / "
        f"{_percentile(s_sorted, 25):.0f} / "
        f"{_percentile(s_sorted, 50):.0f} / "
        f"{_percentile(s_sorted, 75):.0f} / "
        f"{_percentile(s_sorted, 90):.0f}",
        "",
        "## 等级分布",
        "",
        "| 等级 | 占比 |",
        "|---|---:|",
    ]
    for lvl in ["green", "yellow", "orange", "red", "purple"]:
        lines.append(f"| {lvl} | {level_pct.get(lvl, 0):.1f}% |")
    lines.extend([
        "",
        "> 设计预期约 30/30/20/15/5%；偏离过多说明评分体系偏强或偏弱。",
        "",
        "## 规则触发率",
        "",
        "| Rule ID | 触发次数 | 触发率 |",
        "|---|---:|---:|",
    ])
    for rid, count in triggers:
        lines.append(f"| `{rid}` | {count} | {count / n * 100:.1f}% |")
    lines.extend([
        "",
        "## Category 贡献",
        "",
        "| Category | 触发率 | 平均 delta | min | max |",
        "|---|---:|---:|---:|---:|",
    ])
    for s in cat_stats:
        lines.append(
            f"| `{s['category']}` | {s['trigger_rate']:.1f}% | "
            f"{s['mean_delta']:+.1f} | {s['min_delta']:+.0f} | "
            f"{s['max_delta']:+.0f} |"
        )
    lines.extend([
        "",
        "## 价格确认状态分布",
        "",
        "| 状态 | 占比 |",
        "|---|---:|",
    ])
    for st, pct in sorted(pc_pct.items(), key=lambda x: -x[1]):
        lines.append(f"| {st} | {pct:.1f}% |")
    lines.extend([
        "",
        "## 校准建议",
        "",
    ])
    if suggestions:
        for s in suggestions:
            lines.append(f"- {s}")
    else:
        lines.append("- 所有规则触发率在 2%-70% 区间，阈值校准合理。")
    lines.append("")
    return "\n".join(lines)


def write_backtest_report(content: str, reports_dir: Path | str,
                          commodity: str) -> Path:
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    date = datetime.now().strftime("%Y-%m-%d")
    path = out_dir / f"backtest_{commodity}_{date}.md"
    path.write_text(content, encoding="utf-8")
    return path
