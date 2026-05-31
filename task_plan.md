# Task Plan: commodity_radar 基本面风险雷达

**Created:** 2026-05-31
**Status:** Awaiting User Approval (规划完成，待确认后执行)

---

## Goal（目标）

构建一个 Python 项目 `commodity_radar`，每日跟踪白糖、棕榈油、天然橡胶三个品种的基本面指标，自动评分（0-100），生成 Markdown 日报，预留 Telegram/Email/Feishu 预警接口。

**核心原则**：
- 不输出买卖信号，只输出风险描述（偏多/偏空/中性/风险上升/风险下降/需要继续验证）
- 数据源不稳定时不能崩溃，必须 fallback 到 `manual_inputs.yaml`
- 适合 macOS / Linux VPS + cron 定时运行
- 即使完全没有真实数据，也能用 mock data 跑通端到端流程

---

## 关键设计决策（请用户审阅）

### 1. 指标统一数据结构

每条指标记录包含字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| commodity | str | sugar / palm / rubber / common |
| name | str | 指标名（中文）|
| value_num | float\|null | 数值型值 |
| value_text | str\|null | 文本型值（如政策描述）|
| unit | str | 单位（mm, MT, %, USD/bbl 等）|
| source | str | 数据来源（"NOAA CPC" / "MPOB" / "manual"）|
| timestamp | ISO8601 | 数据原始发布/观测时间 |
| fetched_at | ISO8601 | 系统抓取时间 |
| confidence | str | high (自动抓取) / medium (手动) / low (缺失或过期 >7天) |
| is_manual | bool | 是否来自 manual_inputs.yaml |
| notes | str | 备注 |

### 2. SQLite 表结构（data/processed/commodity_radar.db）

- `indicators` — 所有指标的时序快照
- `scores` — 每日评分结果（含 raw_score, final_score, level, change_1d, change_7d, bullish_json, bearish_json, alerts_json）
- `events` — 政策/新闻/异常事件日志
- `fetch_log` — 每次抓取的成败记录

### 3. 评分模型

**算法**：
1. 每条规则（`rules.py` 中的函数）输入当日指标快照，输出 `{applies, score_delta, label, category, side}`
2. 收集所有触发的 deltas → `raw_score = sum(deltas)`
3. `final_score = clamp(raw_score, 0, 100)`
4. 同时按 category 分组统计贡献度，供报告展示
5. 与 SQLite 中昨日/上周分数对比，计算 `score_change_1d`, `score_change_7d`
6. 按阈值映射等级（0-30 绿 / 31-50 黄 / 51-70 橙 / 71-85 红 / 86-100 紫）

**权重的用途**：用户给的分类权重（如"印度天气与政策 30%"）在 v1 中用于报告展示分类占比，不参与最终分数计算（避免双重加权）。如需严格加权，可在 v2 切换为 `final = Σ(category_subscore × weight)`。

### 4. 数据源抓取策略

| 数据源 | 实现方式 | Fallback |
|---|---|---|
| NOAA CPC ENSO | requests + 公开 CSV/TXT 解析 | manual_inputs.yaml |
| MPOB 月报 | requests + HTML 解析（best-effort）| manual_inputs.yaml |
| ANRPC | 几乎全部 manual（付费）| manual_inputs.yaml |
| USDA PSD | requests + 公开 API（无 key 可访问的端点）| manual_inputs.yaml |
| 市场价格（Brent/糖/棕油/橡胶）| yfinance 库 | manual_inputs.yaml |
| 新闻政策 | feedparser RSS（Reuters/USDA GAIN）+ 关键词匹配 | events 表手动录入 |
| 天气降雨距平 | 暂全部 manual（NOAA CPC 月度数据可后续接入）| manual_inputs.yaml |

**异常处理三原则**：
1. 任何 fetcher 失败 → 写 fetch_log + events 表 + 日志 → 继续不中断
2. 自动 fallback 到 manual_inputs.yaml 中对应字段
3. 在报告中标注"该数据为手动输入"或"数据缺失（评分忽略此项）"

### 5. 项目文件清单

完整清单（28 个文件）：

```
commodity_radar/
├── README.md
├── config.yaml                          # 全局配置
├── manual_inputs.yaml                   # 手动数据 + 备用数据
├── requirements.txt
├── .env.example                         # 预警密钥示例
├── main.py                              # CLI 入口
├── data/
│   ├── raw/                             # 原始抓取缓存 + 日志
│   └── processed/                       # SQLite DB 存放位置
├── reports/                             # 生成的日报
└── src/
    ├── __init__.py
    ├── fetchers/
    │   ├── __init__.py
    │   ├── enso.py                      # ENSO/Niño3.4/ONI/SOI
    │   ├── weather.py                   # 区域降雨距平（v1 全 manual）
    │   ├── sugar.py                     # 白糖品种指标
    │   ├── palm.py                      # 棕榈油品种指标
    │   ├── rubber.py                    # 橡胶品种指标
    │   ├── market.py                    # 市场价格（yfinance）
    │   └── news.py                      # RSS 新闻关键词
    ├── indicators/
    │   ├── __init__.py
    │   ├── scoring.py                   # 评分聚合 + 等级 + 变化
    │   └── rules.py                     # 所有规则函数（按品种分类）
    ├── storage/
    │   ├── __init__.py
    │   └── database.py                  # SQLite 封装
    ├── reports/
    │   ├── __init__.py
    │   ├── daily_report.py              # 报告编排
    │   └── markdown_report.py           # Markdown 渲染
    └── alerts/
        ├── __init__.py
        ├── dispatcher.py                # 预警分发（按触发条件）
        ├── telegram.py
        ├── email_alert.py
        └── feishu.py
```

### 6. 依赖（requirements.txt）

```
requests>=2.31
pandas>=2.1
PyYAML>=6.0
python-dotenv>=1.0
yfinance>=0.2.40
feedparser>=6.0
beautifulsoup4>=4.12
lxml>=5.0
jinja2>=3.1
```

Python 3.11+，sqlite3 用标准库。

### 7. CLI 设计（main.py）

```bash
python main.py fetch       # 跑所有 fetcher，写入 indicators 表
python main.py score       # 读取最新指标 → 跑规则 → 写入 scores 表
python main.py report      # 渲染 reports/YYYY-MM-DD_daily_report.md
python main.py run-all     # fetch → score → report → alert
python main.py seed        # 注入 3+ 天模拟数据（首次使用）
```

### 8. 预警逻辑（alerts/dispatcher.py）

触发条件（任一满足即发送）：
- 单品种 final_score >= 71
- 单品种 score_change_1d >= 10
- 单品种 score_change_7d >= 20
- events 表中出现关键政策关键词（印度糖出口禁令、印尼 B50、MPOB 库存阈值穿越等）

v1：所有通道默认 dry-run，打印到 stdout；通过 `.env` 配置 `TELEGRAM_TOKEN` / `EMAIL_SMTP_*` / `FEISHU_WEBHOOK_URL` 即激活。

---

## Phases（执行阶段）

### Phase 1: 基础设施 — Pending
- [ ] 创建目录结构（data/raw, data/processed, reports, src/**）
- [ ] 写 requirements.txt
- [ ] 写 config.yaml（品种列表、权重、阈值、路径）
- [ ] 写 .env.example
- [ ] storage/database.py — SQLite 初始化、insert/query 封装

### Phase 2: 手动输入兜底层 — Pending
- [ ] 编写完整 manual_inputs.yaml（覆盖 spec 中所有指标）
- [ ] 编写解析器（含 schema 校验、缺失字段告警）

### Phase 3: 评分引擎 — Pending
- [ ] rules.py — 实现 spec 中全部规则：
  - ENSO 共同规则（5 条）
  - 白糖规则（约 11 条）
  - 棕榈油规则（约 13 条，含 -10/-15 负值）
  - 橡胶规则（约 13 条，含 -10/-15 负值）
- [ ] scoring.py — 聚合、clamp、等级、变化计算

### Phase 4: 报告生成 — Pending
- [ ] markdown_report.py — Jinja2 模板按 spec 七节渲染
- [ ] daily_report.py — 编排

### Phase 5: Fetcher 实装 + 容错 — Pending
- [ ] enso.py — NOAA CPC Niño3.4 / ONI（真实抓取 + manual fallback）
- [ ] market.py — yfinance（Brent=BZ=F, 糖=SB=F, 棕油=KPO 替代, 橡胶=TR=F 不一定可用）
- [ ] news.py — Reuters / USDA RSS + 关键词
- [ ] sugar.py / palm.py / rubber.py — 编排型 fetcher，主要从 manual + market + news 拉取
- [ ] weather.py — v1 全 manual
- [ ] 所有 fetcher 接入 fetch_log + try/except

### Phase 6: 预警通道 — Pending
- [ ] dispatcher.py — 触发条件判断
- [ ] telegram.py / email_alert.py / feishu.py — 各通道发送函数（dry-run + 真实）

### Phase 7: CLI 入口 — Pending
- [ ] main.py — argparse 子命令 fetch/score/report/run-all/seed

### Phase 8: 模拟数据 — Pending
- [ ] seed_data.py 或 main.py seed — 写入过去 7 天历史 indicators + scores（让 score_change_1d/7d 有意义）
- [ ] manual_inputs.yaml 默认值填合理示例

### Phase 9: 文档 — Pending
- [ ] README.md — 安装/配置/运行/cron 示例/项目原理/免责声明

### Phase 10: 端到端冒烟测试 — Pending
- [ ] `pip install -r requirements.txt`
- [ ] `python main.py seed`
- [ ] `python main.py run-all`
- [ ] 检查 reports/2026-05-31_daily_report.md 是否生成
- [ ] 检查 SQLite 表是否有数据
- [ ] 模拟某 fetcher 抛异常，验证不崩溃

---

## 验收标准（Acceptance Criteria）

1. ✅ 项目目录完全匹配 spec 给出的结构
2. ✅ `pip install -r requirements.txt && python main.py run-all` 在断网状态也能跑通
3. ✅ 生成 `reports/2026-05-31_daily_report.md`，含三品种评分表 + 详细指标表 + 预警章节
4. ✅ SQLite 包含至少 7 天的 indicators 和 scores 历史（mock 数据）
5. ✅ score_change_1d 和 score_change_7d 在报告中显示真实数字（非 0）
6. ✅ 报告中无"买入/卖出"字样，只有偏多/偏空/中性/风险上升/风险下降/需要继续验证
7. ✅ 至少一个 fetcher 故意失败时，程序不崩溃且报告标注"数据为手动输入"
8. ✅ README 包含完整 cron 示例（如 `0 8 * * * cd /opt/commodity_radar && /opt/commodity_radar/.venv/bin/python main.py run-all`）

---

## Decisions Log
- 2026-05-31: 权重不参与最终分数计算（v1 仅用于报告展示），避免双重加权 + 简化实现
- 2026-05-31: 数据基准日定为 2026-05-31（今日），seed 数据回填到 2026-05-24
- 2026-05-31: yfinance 作为市场价格首选源（无 API key、覆盖广），失败时 manual fallback
- 2026-05-31: 预警通道 v1 dry-run，避免误发送
- 2026-05-31: ✅ 用户确认 ENSO 真实抓 NOAA + manual 兜底
- 2026-05-31: ✅ 用户确认市场价格用 yfinance
- 2026-05-31: ✅ 用户确认 v1 无 Web 仪表盘
- 2026-05-31: ✅ 用户要求加规则函数单元测试 → 新增 tests/ 目录 + Phase 11

## Open Questions
（已全部确认，开始执行）

## Errors & Blockers
（暂无）
