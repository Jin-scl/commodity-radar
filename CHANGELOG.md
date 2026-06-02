# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和
[Semantic Versioning](https://semver.org/lang/zh-CN/) 规范。

## [1.0.0] - 2026-06-02

首个稳定版本。从纯规则脚本演进为完整的基本面风险解释系统。

### 新增（评分体系 v3）

- **数据置信度衰减**：规则贡献按 `confidence_mult`（high×1.0 / medium×0.8 / low×0.4）衰减
- **Freshness 自动降级**：超过 freshness 阈值的数据 confidence 自动从 high → medium → low
- **Category 封顶**：同 category 总贡献被 cap（按 `commodity.category` 精细化），抑制重复加分
- **预期差规则**：6 条新规则对比 actual vs `_expected`（MPOB 库存/产量/出口 + 印度/泰国/巴西糖产量）
- **季节性基准**：5 条新规则对比 actual vs `_5y_avg`（MPOB 库存/出口 + 中印需求合计 + 青岛库存 + 轮胎开工）
- **价格确认模块**：6 状态（confirmed / partial / weak / diverging / **price_leading** / price_watch / neutral / no_data）
  - 信号权重 × 数据置信度系数加权
  - 低置信度自动降级 status（避免低质量数据强结论）
- **等级穿越预警**：风险等级跨档自动触发（比纯阈值更稳）
- **较昨日变化来源**：报告含 added / removed / persistent rule ids diff
- **双置信度**：`confidence_score`（整体）+ `triggered_confidence`（真正推动分数的字段）

### 新增（数据层）

- ENSO 真实抓取 NOAA CPC（Niño 3.4 周度 + ONI 月度）+ partial fallback
- yfinance 市场价格（Brent / 豆油）+ manual 补齐（菜油 / 葵油 / 丁二烯等）
- RSS 新闻关键词 → events 表 + 预警
- 22 个新 manual 字段（`_expected` × 6, `_5y_avg` × 6, 价格信号 × 10）

### 新增（工程）

- **Monte Carlo 回测**（`python main.py backtest`）：检验评分体系稳定性 + 自动阈值校准建议
- **Obsidian 双写**：报告同时写入本地 reports/ 和 Obsidian vault + YAML frontmatter
- `.env` 覆盖 Obsidian 配置（公开 repo 默认 disable，本地启用）
- SQLite schema：indicators / scores / events / fetch_log 四表 + 幂等迁移
- `RuleResult.input_keys` ContextVar 自动追踪（零规则函数修改）
- `as_of_date` 真实按日期回放（`--date YYYY-MM-DD`）

### 修复（共 5 轮审查 ~ 30 个 P1/P2 bug）

主要：
- ENSO Niño 3.4 列解析错位（之前取了 Niño4 SSTA）
- seed 数据用 `source='seed'` 标记，默认排除避免污染最新快照
- `cmd_report` 默认 `persist=False`，不再误清 scores.triggered_alerts_json
- `get_recent_events` 兼容 date-only timestamp，按 00:00 精筛 24h 窗口
- market fetcher 部分成功时合并 manual 补齐（之前菜油/葵油等静默丢失）
- `evaluate_alerts(score_date=...)` 按日期回放事件，不再混入今天 events
- `RuleResult.evidence` ≠ 触发字段：改用 `input_keys` 算置信度
- `cmd_run_all` 用 `effective_date = args.date or today_str()` 统一日期窗口

### 测试

- 163 单元测试覆盖：规则（80）/ 数据库（5）/ 评分 v2（6）/ freshness（12）/ 价格确认（22）/
  预期差（15）/ 季节性（15）/ 第四第五轮修复（14）/ ENSO 解析（4）

### 文档

- README 含完整评分模型说明 + 数据源标注 + cron 示例 + 价格确认状态表
- progress.md / task_plan.md / findings.md 保留开发历史

## 项目原则

- **不输出买卖信号** — 仅输出风险方向（偏多 / 偏空 / 中性 / 风险上升 / 风险下降 / 需要继续验证）
- **不稳定数据自动 fallback** — manual_inputs.yaml 兜底，报告显式标注数据来源
- **可解释优先** — 每条规则触发都有具体 evidence + label，不是黑箱评分

[1.0.0]: https://github.com/Jin-scl/commodity-radar/releases/tag/v1.0.0
