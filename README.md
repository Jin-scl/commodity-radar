# commodity_radar

> 白糖 / 棕榈油 / 天然橡胶 的基本面风险雷达。
> 每日跟踪关键指标，输出 0-100 风险分 + Markdown 日报 + Telegram/Email/飞书 预警。

**重要原则**：本项目**不输出买卖信号**，只输出风险描述（偏多 / 偏空 / 中性 / 风险上升 / 风险下降 / 需要继续验证）。

---

## 特性

- ✅ ENSO（Niño 3.4 / ONI / SOI）自动抓取 NOAA CPC
- ✅ 市场价格用 yfinance（Brent / 豆油等）
- ✅ MPOB / ANRPC / 印度糖业等不稳定数据 → `manual_inputs.yaml` 手动维护
- ✅ 任何 fetcher 失败 → 自动 fallback + 报告显式标注「该数据为手动输入」
- ✅ SQLite 存储所有指标和评分历史，支持 1日 / 7日 风险变化对比
- ✅ 触发阈值后发送预警（Telegram / Email / 飞书 Webhook）
- ✅ **Obsidian 集成**：报告自动写入 vault + YAML frontmatter，支持 Dataview 查询
- ✅ macOS / Linux / VPS 通用，cron 友好

---

## 安装

需要 **Python 3.11+**。

```bash
cd commodity_radar
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

依赖：requests / pandas / PyYAML / python-dotenv / yfinance / feedparser / beautifulsoup4 / lxml / jinja2 / pytest。

---

## 首次使用：3 步

```bash
# 1) 注入过去 8 天历史模拟数据（让 1日 / 7日 变化有意义）
python main.py seed

# 2) 完整跑一遍：抓取 → 评分 → 报告 → 预警
python main.py run-all

# 3) 打开报告
open reports/$(date +%F)_daily_report.md
```

第一次跑完之后，`data/processed/commodity_radar.db` 会包含 ~8 天历史 + 今日抓取数据，
`reports/` 下会出现 Markdown 日报。

---

## 日常使用

### 子命令

| 命令 | 作用 |
|---|---|
| `python main.py fetch` | 跑所有 fetcher，写入 SQLite |
| `python main.py score` | 读最新指标 → 跑规则 → 写 scores 表 |
| `python main.py score --date 2026-05-30` | 指定日期重算 |
| `python main.py report` | 生成 Markdown 报告 |
| `python main.py report --with-alerts` | 报告内包含预警章节 |
| `python main.py run-all` | fetch → score → report → alert（cron 用） |
| `python main.py seed --days 14` | 注入 14 天历史模拟数据 |

### 维护手动数据

打开 `manual_inputs.yaml`，按品种修改对应字段：

```yaml
sugar:
  maharashtra_rainfall_anomaly_pct:
    value: -25.0           # 改成你看到的最新数据
    unit: "%"
    timestamp: "2026-06-01"
    source: "IMD"          # 可选，默认 manual
    notes: "马哈拉施特拉邦本周降雨"
```

YAML 简写也支持：`maharashtra_rainfall_anomaly_pct: -25.0`（仅当只有 value 时）。

---

## 配置预警通道

复制 `.env.example` 为 `.env`，按需填写：

```bash
cp .env.example .env
vim .env
```

支持通道：

- **Telegram**：`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- **Email (SMTP)**：`EMAIL_SMTP_HOST` / `PORT` / `USER` / `PASSWORD` / `FROM` / `TO`
- **飞书 Webhook**：`FEISHU_WEBHOOK_URL`

只要任一通道填了，就会真发送；未填的通道自动 skip。

默认 `ALERTS_DRY_RUN=true`，预警只打印到日志、不实际发送。生产用时改为 `false`。

### 触发条件（`config.yaml::alerts`）

- 单品种 `final_score >= 71`
- 单品种 1 日上升 ≥ 10
- 单品种 7 日上升 ≥ 20
- `events` 表里出现关键政策关键词（印度糖出口禁令 / 印尼 B50 / MPOB 库存阈值穿越…）

---

## Obsidian 集成

报告会自动**双写**到 Obsidian vault，方便用 Obsidian 看历史 / 用 Dataview 查询。

`config.yaml::obsidian`：

```yaml
obsidian:
  enabled: true                              # 默认 false；改 true 启用
  vault_path: "~/Documents/Obsidian Vault"   # 改成你的 vault 路径（支持 ~）
  subfolder: "commodity_radar"
  create_index: true                         # 首次写入时自动生成 README.md 含 Dataview 示例
```

每篇报告顶部含 YAML frontmatter：

```yaml
---
date: 2026-05-31
type: commodity-radar-daily
tags: [commodity, daily-report, sugar, palm, rubber]
sugar_score: 25
sugar_level: green
palm_score: 31
palm_level: yellow
rubber_score: 45
rubber_level: yellow
alert_count: 0
---
```

vault 子目录里自动生成的 `README.md` 包含 Dataview 查询示例（需安装 Dataview 插件）：

````markdown
```dataview
TABLE sugar_score, palm_score, rubber_score, alert_count
FROM "commodity_radar"
WHERE type = "commodity-radar-daily"
SORT date DESC
```
````

vault 路径不存在或写入失败：本地 `reports/` 仍正常写入；只在日志里 warning，不影响主流程。

---

## cron 定时

VPS 上推荐每天早晨跑一次：

```bash
# crontab -e
0 8 * * * cd /opt/commodity_radar && /opt/commodity_radar/.venv/bin/python main.py run-all >> /opt/commodity_radar/data/raw/cron.log 2>&1
```

如果你想分钟级监控价格而每天只发一次报告：

```bash
# 每 30 分钟更新一次市场价格 + 重算评分（不发送预警，不出报告）
*/30 * * * * cd /opt/commodity_radar && /opt/commodity_radar/.venv/bin/python main.py fetch && /opt/commodity_radar/.venv/bin/python main.py score

# 每天早上 8:00 发送完整日报 + 预警
0 8 * * *    cd /opt/commodity_radar && /opt/commodity_radar/.venv/bin/python main.py run-all
```

---

## 项目结构

```
commodity_radar/
├── main.py                          # CLI 入口（5 个子命令）
├── config.yaml                      # 全局配置：品种 / 权重 / 阈值
├── manual_inputs.yaml               # 手动数据 + 兜底数据
├── requirements.txt
├── .env.example
├── README.md
├── data/
│   ├── raw/                         # 日志 + 原始缓存
│   └── processed/
│       └── commodity_radar.db       # SQLite (indicators/scores/events/fetch_log)
├── reports/
│   └── YYYY-MM-DD_daily_report.md
├── tests/                           # pytest 单元测试
└── src/
    ├── utils.py                     # 配置/日志/manual 解析公共工具
    ├── fetchers/
    │   ├── base.py                  # @fetcher 装饰器：异常+fallback+计时
    │   ├── enso.py                  # NOAA CPC ENSO（真实抓取）
    │   ├── market.py                # yfinance 市场价格
    │   ├── news.py                  # RSS 新闻关键词
    │   ├── weather.py               # v1 全 manual
    │   ├── sugar.py / palm.py / rubber.py    # 编排型
    │   └── orchestrator.py
    ├── indicators/
    │   ├── rules.py                 # ~42 条评分规则
    │   └── scoring.py               # 聚合 + clamp + 等级 + 1日/7日变化
    ├── storage/
    │   └── database.py              # SQLite schema + CRUD
    ├── reports/
    │   ├── markdown_report.py       # Jinja2 模板
    │   └── daily_report.py          # 编排
    └── alerts/
        ├── dispatcher.py            # 触发条件 + 分发
        ├── telegram.py / email_alert.py / feishu.py
```

---

## 评分模型

**算法**：
1. 每条规则（`src/indicators/rules.py`）检查 snapshot，输出 `(label, delta, category, side)`
2. `raw_score = Σ deltas`（正=利多，负=利空）
3. `final_score = clamp(raw_score, 0, 100)`
4. 等级映射（`config.yaml::risk_levels`）：
   - 0-30 🟢 绿色（无明显利多）
   - 31-50 🟡 黄色（局部扰动）
   - 51-70 🟠 橙色（多项指标偏多）
   - 71-85 🔴 红色（强供需冲击）
   - 86-100 🟣 紫色（极端行情风险）
5. 与昨日 / 上周分数对比 → `score_change_1d`, `score_change_7d`

**分类权重**（`config.yaml::weights`）v1 仅用于报告分类展示，不参与最终分数计算。

---

## 数据源说明

> 🔵 = 真实自动抓取  ⚪ = 仍依赖 manual_inputs.yaml

| 数据源 | 实装 | 备注 |
|---|---|---|
| NOAA CPC Niño 3.4 (周度 SSTA) | 🔵 | wksst9120.for 文本解析；正则按列位置取 Niño34 SSTA |
| NOAA CPC ONI (月度) | 🔵 | NOAA 接口 SSL 不稳时自动 fallback manual |
| yfinance Brent (BZ=F) | 🔵 | 含连续上涨天数派生 |
| yfinance 豆油 (ZL=F) | 🔵 | |
| 棕榈油 / 橡胶期货 | ⚪ | yfinance 覆盖不稳；manual 兜底 |
| MPOB（马来棕油月报） | ⚪ | v2 可加 HTML 解析 |
| ANRPC（天然橡胶产量） | ⚪ | 付费数据；只能 manual |
| ISMA（印度糖业） | ⚪ | |
| USDA RSS 政策报告 | 🔵 | feedparser + 关键词命中写 events 表 |
| 中国轮胎开工率 / 青岛库存 | ⚪ | v2 可接 akshare |
| 菜油 / 葵油 / 丁二烯 / 合成胶 | ⚪ | market fetcher 会从 yfinance 已抓字段之外，自动从 manual_inputs.yaml::market **补齐** |

数据置信度（high / medium / low）会**衰减规则贡献**：

- high (真实抓取) → 100% 计分
- medium (manual) → 80%
- low (历史 seed / 过期) → 40%

所以同样触发"印度产量下调 +15"，high 数据贡献 +15，manual 贡献 +12，过期数据只贡献 +6。
报告总览表里有"置信度"列，显示该品种当日数据整体置信度（0-100）。

国内 VPS 注意：yfinance 可能需要代理。`config.yaml` 里可关闭单个 fetcher：

```yaml
fetchers:
  market: false   # 关掉 yfinance，全部走 manual_inputs.yaml::market
```

---

## 单元测试

```bash
pytest tests/
```

覆盖 `src/indicators/rules.py` 中所有规则的正向/反向触发场景。

---

## 免责声明

本项目仅作为基本面**风险监控**工具，所有数据和结论：

- 不构成投资建议
- 不预测价格走势
- 不输出买卖信号
- 仅供研究与学习

数据来自公开来源或手动维护，可能存在延迟、错误、不完整。决策请独立验证。

---

## 贡献

- 想接入新的数据源？在 `src/fetchers/` 加一个 fetcher，用 `@fetcher` 装饰即可
- 想加新规则？在 `src/indicators/rules.py` 写一个 `rule_xxx(snap)` 并加入对应规则列表
- 想加新通道？参考 `src/alerts/feishu.py`
