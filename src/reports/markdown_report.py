"""Markdown 报告渲染 —— 用 jinja2 模板生成 spec 第七节定义的报告结构。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment

# 品种中文名映射
COMMODITY_LABELS = {
    "sugar": "白糖",
    "palm": "棕榈油",
    "rubber": "天然橡胶",
}


FRONTMATTER_TEMPLATE = """---
date: {{ date }}
type: commodity-radar-daily
tags:
  - commodity
  - daily-report
{%- for c in commodities %}
  - {{ c.commodity }}
{%- endfor %}
{%- for c in commodities %}
{{ c.commodity }}_score: {{ c.final_score }}
{{ c.commodity }}_level: {{ c.risk_level }}
{{ c.commodity }}_confidence: {{ c.confidence_score or 0 }}
{{ c.commodity }}_triggered_confidence: {{ c.triggered_confidence if c.triggered_confidence is not none else 0 }}
{{ c.commodity }}_change_1d: {{ c.score_change_1d if c.score_change_1d is not none else 0 }}
{{ c.commodity }}_change_7d: {{ c.score_change_7d if c.score_change_7d is not none else 0 }}
{%- endfor %}
alert_count: {{ alerts | length }}
generated_at: {{ generated_at }}
---

"""


REPORT_TEMPLATE = """# Commodity Radar Daily Report - {{ date }}

> 本报告仅作基本面风险监控；不构成任何买卖建议。
> 用语规范：偏多 / 偏空 / 中性 / 风险上升 / 风险下降 / 需要继续验证。

## 总览

| 品种 | 风险分 | 等级 | 整体置信度 | 触发置信度 | 1日变化 | 7日变化 | 结论 |
|---|---:|---|---:|---:|---:|---:|---|
{% for c in commodities -%}
| {{ labels[c.commodity] }} | {{ c.final_score }} | {{ c.risk_level_label }} | {{ c.confidence_score or '—' }} | {{ c.triggered_confidence if c.triggered_confidence is not none else '—' }} | {{ fmt_change(c.score_change_1d) }} | {{ fmt_change(c.score_change_7d) }} | {{ c.conclusion }} |
{% endfor %}

> **整体置信度** = 所有指标置信度均值；**触发置信度** = 真正推动分数的指标的置信度（更重要）。差距大说明评分由少数高质量数据驱动，或受多数低质量数据干扰。

{% for c in commodities %}
## {{ labels[c.commodity] }}

### 今日结论
**{{ c.risk_level_label }}（{{ c.final_score }} 分 ｜ 整体置信度 {{ c.confidence_score or '—' }}/100，触发置信度 {{ c.triggered_confidence if c.triggered_confidence is not none else '—' }}/100）** — {{ c.conclusion }}

{% if c.regime_change -%}
> ⚠️ **等级穿越**：{{ c.regime_change.from }} → {{ c.regime_change.to }}
{% endif %}

- 触发规则数：**{{ c.triggered_count }}**
- 分类贡献（已封顶 ±25 / category）：{% for k, v in c.category_breakdown.items() %}`{{ k }}` {{ "+" if v > 0 else "" }}{{ v }}{% if not loop.last %} · {% endif %}{% endfor %}
{% if c.neutral_flags %}
- 中性标记：{% for f in c.neutral_flags %}{{ f.flag }}{% if not loop.last %} / {% endif %}{% endfor %}
{% endif %}

{% if c.factor_diff and (c.factor_diff.added or c.factor_diff.removed) -%}
### 较昨日变化来源
{% if c.factor_diff.added -%}
**新增触发** ({{ c.factor_diff.added | length }} 条)：
{% for rid in c.factor_diff.added -%}
- `{{ rid }}`
{% endfor %}
{%- endif %}
{% if c.factor_diff.removed -%}
**消失触发** ({{ c.factor_diff.removed | length }} 条)：
{% for rid in c.factor_diff.removed -%}
- `{{ rid }}`
{% endfor %}
{%- endif %}
{%- endif %}

### 主要利多
{% if c.bullish_factors -%}
{% for f in c.bullish_factors -%}
- **+{{ f.score_delta }}** ｜ {{ f.label }}  *(分类: {{ f.category }})*
{% endfor %}
{%- else -%}
- *无*
{%- endif %}

### 主要利空
{% if c.bearish_factors -%}
{% for f in c.bearish_factors -%}
- **{{ f.score_delta }}** ｜ {{ f.label }}  *(分类: {{ f.category }})*
{% endfor %}
{%- else -%}
- *无*
{%- endif %}

### 关键指标
| 指标 | 最新值 | 单位 | 变化/说明 | 数据来源 | 更新时间 | 置信度 |
|---|---:|---|---|---|---|---|
{% for ind in c.key_indicators -%}
| {{ ind.name }} | {{ ind.value_display }} | {{ ind.unit or '' }} | {{ ind.note or '' }} | {{ ind.source or '' }} | {{ ind.timestamp or '' }} | {{ ind.confidence }}{% if ind.is_manual %} *(手动)*{% endif %} |
{% endfor %}

{% endfor %}

## 预警

{% if alerts -%}
{% for a in alerts -%}
- **[{{ a.severity|upper }}]** {{ labels.get(a.commodity, a.commodity) }} ｜ {{ a.message }}
{% endfor %}
{%- else -%}
- *本期无触发预警*
{%- endif %}

## 数据缺失与注意事项

{% if missing_notes -%}
{% for n in missing_notes -%}
- {{ n }}
{% endfor %}
{%- else -%}
- *本期数据完整*
{%- endif %}

---

*生成时间：{{ generated_at }}*
*数据原则：不稳定数据自动 fallback 到 manual_inputs.yaml，手动数据会在表格中标注。*
"""


def _format_change(v):
    if v is None:
        return "—"
    if v > 0:
        return f"+{v}"
    return f"{v}"


def _format_value(ind: dict) -> str:
    if ind.get("value_num") is not None:
        n = ind["value_num"]
        if abs(n) >= 1000:
            return f"{n:,.0f}"
        if n == int(n):
            return f"{int(n)}"
        return f"{n:.2f}"
    if ind.get("value_text"):
        return ind["value_text"]
    return "—"


def select_key_indicators(commodity: str, all_indicators: list[dict],
                          max_n: int = 15) -> list[dict]:
    """按品种挑选最关键的指标在报告里展示。
    优先级：每个 commodity 维护一个"核心指标白名单"，按出现顺序显示；
    超出 max_n 后截断。
    """
    priority = {
        "sugar": [
            "nino34", "oni",
            "india_monsoon_anomaly_pct", "maharashtra_rainfall_anomaly_pct",
            "karnataka_rainfall_anomaly_pct", "india_sugar_production_mt",
            "india_sugar_production_change_mt", "india_export_policy",
            "brazil_sugar_mix_pct", "brazil_sugar_mix_change_pp",
            "brazil_ethanol_price_brl", "brent_price_usd",
            "thailand_rainfall_below_normal_weeks",
            "thailand_sugar_production_mt", "china_sugar_import_mt",
        ],
        "palm": [
            "indonesia_core_rainfall_below_normal_weeks",
            "indonesia_cpo_production_mt", "indonesia_cpo_production_change_mt",
            "indonesia_biodiesel_mandate", "indonesia_export_policy",
            "mpob_cpo_production_mt", "mpob_end_stock_mt",
            "mpob_stock_mom_change_pct", "mpob_export_mt",
            "mpob_export_mom_change_pct", "mpob_oer_pct",
            "brent_price_usd", "soybean_oil_price_usd",
            "china_palm_import_mt", "china_port_stock_mt",
        ],
        "rubber": [
            "thailand_south_extreme_event", "thai_field_latex_price_thb",
            "thai_cup_lump_price_thb", "anrpc_production_forecast_kt",
            "anrpc_forecast_change_kt",
            "china_semi_steel_tire_operating_rate_pct",
            "china_full_steel_tire_operating_rate_pct",
            "china_tire_export_yoy_pct",
            "qingdao_bonded_stock_kt", "qingdao_bonded_stock_change_pct",
            "shfe_ru_stock_kt", "ine_nr20_stock_kt",
            "brent_price_usd", "butadiene_price_usd",
            "br_synthetic_price_usd",
        ],
    }
    by_name = {i["name"]: i for i in all_indicators}
    out = []
    for n in priority.get(commodity, []):
        if n in by_name:
            ind = dict(by_name[n])
            ind["value_display"] = _format_value(ind)
            out.append(ind)
        if len(out) >= max_n:
            break
    return out


def build_missing_notes(snapshot: dict, key_names: list[str]) -> list[str]:
    notes = []
    for n in key_names:
        if n not in snapshot or snapshot[n].get("value") in (None, ""):
            notes.append(f"指标 `{n}` 缺失，本期评分忽略此项")
        elif snapshot[n].get("is_manual"):
            notes.append(f"指标 `{n}` 使用手动输入（manual_inputs.yaml）")
        elif snapshot[n].get("confidence") == "low":
            notes.append(f"指标 `{n}` 数据较旧（confidence=low）")
    # 去重并保持顺序
    seen = set()
    uniq = []
    for n in notes:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq


def render_report(
    score_date: str,
    scores: list[dict],
    indicators_by_commodity: dict[str, list[dict]],
    snapshots_by_commodity: dict[str, dict],
    alerts: list[dict],
    include_frontmatter: bool = True,
) -> str:
    """主渲染入口。
    scores: evaluate_all 的 value 列表（带 commodity）
    indicators_by_commodity: {commodity: [indicator dict]} 用于关键指标表
    snapshots_by_commodity: 同上但是扁平 snapshot，用于 missing_notes
    alerts: dispatcher 返回的预警列表 [{commodity, severity, message}]
    include_frontmatter: 是否在报告顶部加 YAML frontmatter（供 Obsidian 用）
    """
    env = Environment(trim_blocks=False, lstrip_blocks=False)
    env.globals["fmt_change"] = _format_change

    enriched = []
    missing = []
    for s in scores:
        c = s["commodity"]
        all_inds = indicators_by_commodity.get(c, [])
        s_copy = dict(s)
        s_copy["key_indicators"] = select_key_indicators(c, all_inds)
        enriched.append(s_copy)
        snap = snapshots_by_commodity.get(c, {})
        missing.extend(build_missing_notes(snap, [i["name"] for i in
                                                  s_copy["key_indicators"]]))

    generated_at = datetime.now().isoformat(timespec="seconds")
    body_tpl = env.from_string(REPORT_TEMPLATE)
    body = body_tpl.render(
        date=score_date,
        commodities=enriched,
        labels=COMMODITY_LABELS,
        alerts=alerts,
        missing_notes=missing,
        generated_at=generated_at,
    )
    if include_frontmatter:
        fm_tpl = env.from_string(FRONTMATTER_TEMPLATE)
        fm = fm_tpl.render(
            date=score_date,
            commodities=enriched,
            alerts=alerts,
            generated_at=generated_at,
        )
        return fm + body
    return body


def write_report(content: str, reports_dir: Path | str,
                 score_date: Optional[str] = None,
                 obsidian_dir: Optional[Path | str] = None,
                 also_create_index: bool = False) -> list[Path]:
    """写本地 reports/ + 可选 Obsidian vault 子目录。
    返回所有成功写入的路径列表。
    """
    date = score_date or datetime.now().strftime("%Y-%m-%d")
    filename = f"{date}_daily_report.md"
    paths: list[Path] = []

    # 1) 本地副本
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    local_path = out_dir / filename
    local_path.write_text(content, encoding="utf-8")
    paths.append(local_path)

    # 2) Obsidian vault（如果配置了）
    if obsidian_dir:
        ob_dir = Path(obsidian_dir).expanduser()
        try:
            ob_dir.mkdir(parents=True, exist_ok=True)
            ob_path = ob_dir / filename
            ob_path.write_text(content, encoding="utf-8")
            paths.append(ob_path)
            if also_create_index:
                _ensure_obsidian_index(ob_dir)
        except OSError as e:
            # vault 路径不存在 / 权限问题：不影响本地写入
            import logging
            logging.getLogger("commodity_radar").warning(
                "Obsidian write failed (%s): %s", ob_dir, e)

    return paths


def _ensure_obsidian_index(vault_subfolder: Path) -> None:
    """在 vault 子目录下首次写入时创建 README.md 索引（含 Dataview 查询提示）。"""
    index = vault_subfolder / "README.md"
    if index.exists():
        return
    content = """# Commodity Radar

每日基本面风险雷达报告（白糖 / 棕榈油 / 天然橡胶）。

## Dataview 查询示例

按日期降序列出所有报告及评分：

````dataview
TABLE
  sugar_score, sugar_level,
  palm_score, palm_level,
  rubber_score, rubber_level,
  alert_count
FROM "commodity_radar"
WHERE type = "commodity-radar-daily"
SORT date DESC
````

仅显示有预警的日期：

````dataview
TABLE sugar_score, palm_score, rubber_score, alert_count
FROM "commodity_radar"
WHERE type = "commodity-radar-daily" AND alert_count > 0
SORT date DESC
````

## 注意

- 报告由 [commodity_radar](https://github.com/) Python 项目自动生成
- 不构成任何买卖建议；仅供基本面风险监控
"""
    index.write_text(content, encoding="utf-8")
