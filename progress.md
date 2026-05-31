# Progress Log — commodity_radar

## Session 2026-05-31
- 14:00 创建 task_plan.md / findings.md / progress.md
- 14:05 规划完成，用户确认 4 个开放问题后开始执行（加规则单元测试 → 新增 Phase 11）
- 22:00-22:15 Phase 1-11 全部完成
- 22:16 端到端冒烟通过：seed + run-all + 报告生成 + ENSO/yfinance 真实抓取
- 22:17 故意失败测试通过：URL 改无效 → fallback 自动触发 → 6 manual records 加载，is_manual=True

**最终状态：全部完成**

## 验收结果

| 验收项 | 状态 |
|---|---|
| 目录结构匹配 spec | ✅ |
| `pip install -r requirements.txt && python main.py run-all` | ✅ macOS Python 3.14.4 跑通 |
| 报告生成（含三品种 + 详细指标 + 预警） | ✅ reports/2026-05-31_daily_report.md |
| SQLite 含 ≥7 天历史 | ✅ 832 indicator rows + 24 scores |
| score_change_1d / 7d 显示真实数字 | ✅ 白糖 7d +10, 棕榈油 7d -8 |
| 报告无买卖字样，只有偏多/偏空/中性等 | ✅ |
| Fetcher 故意失败不崩溃 + fallback 标注 | ✅ 验证通过 |
| README 含 cron 示例 | ✅ |
| 80 个规则单元测试 | ✅ all passed in 0.06s |
| ENSO 真实抓取 NOAA | ✅ Niño 3.4 = 1.0°C from NOAA CPC weekly |
| yfinance 真实抓取 | ✅ Brent 91.12 / Soybean Oil 77.72 |

## Phase 12 — Obsidian 集成（2026-05-31 22:24）

- 报告双写到本地 reports/ 和 Obsidian vault 子目录（`config.yaml::obsidian.vault_path` 配置）
- 报告顶部加 YAML frontmatter (date/type/tags/sugar_score 等)
- vault 子目录首次写入时自动生成 README.md 含 Dataview 查询示例
- vault 路径不存在或权限错误时仅 warning，不影响本地写入

## Phase 13 — 深度 bug 检查 + 优化（2026-05-31 22:30）

修复 5 个 bug：

| 编号 | 严重度 | 位置 | 修复 |
|---|---|---|---|
| A | 重要 | run-all + generate | evaluate_all 重复执行 2 次 → 加 precomputed_results 参数，只算一次 |
| B | 重要 | persist_scores | 每个 commodity 的 triggered_alerts_json 含全部预警 → 新增 _partition_alerts_by_commodity，按 commodity 过滤 + 'all'/'common' 全局事件广播 |
| C | 重要 | sugar/palm/rubber fetcher | manual `snapshot_date` 作 default timestamp → 改为今天，避免历史 seed 倒挂当日数据 |
| D | 中 | get_indicator_history | datetime.now().isoformat() 含时分秒，与日期格式字典序比较行为不一致 → 改为日期字符串 |
| E | 小 | generate signature | 改 docstring 反映真实返回（本地路径作为主路径，Obsidian 由 write_report 内部处理）|

回归测试：80 个单元测试全过；run-all 端到端通过；Obsidian 双写正确。
