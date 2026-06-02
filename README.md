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
| `python main.py score --date 2026-05-30` | **按日期回放**：只取该日期及之前的快照重算 |
| `python main.py report` | 生成 Markdown 报告（**不动 scores**，安全多次跑） |
| `python main.py report --with-alerts` | 报告内包含预警章节（仍不持久化）|
| `python main.py run-all` | fetch → score → report → alert（cron 用，唯一会写 scores 的） |
| `python main.py seed --days 14` | 注入 14 天历史模拟数据 (`source='seed'`，不污染最新快照) |

> `--date` 真实按日期回放（`timestamp <= score_date` 过滤），所以 `score --date 2026-05-30` 不会用 5-31 之后写入的数据。
> `report` 单独跑**不会清空** `scores.triggered_alerts_json`；要刷新预警必须用 `run-all`。

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
- **等级穿越** (regime change)：风险等级跨档（绿→黄 / 黄→橙 / 橙→红 / 红→紫）；比纯阈值更稳，避免分数刚好卡阈值反复横跳
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

### 用 `.env` 覆盖 Obsidian 配置（推荐）

公开仓库的 `config.yaml::obsidian.enabled` 默认 **false**（避免别人 clone 后意外写入自己的 vault）。
本地使用时不要改 `config.yaml`，用 `.env`（被 `.gitignore` 排除）：

```bash
cp .env.example .env
# 在 .env 里取消注释这几行：
OBSIDIAN_ENABLED=true
OBSIDIAN_VAULT_PATH=~/Documents/Obsidian Vault
OBSIDIAN_SUBFOLDER=commodity_radar
```

这样升级仓库时 `git pull` 不会冲突，也不会把本地路径泄露到提交里。

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

**算法**（v2 升级版）：
1. 每条规则（`src/indicators/rules.py`）检查 snapshot，输出 `(label, delta, category, side)`
2. **数据置信度衰减**：每条规则按 evidence 中**最低 confidence** 衰减 delta
   - high (真实抓取) × 1.0
   - medium (manual) × 0.8
   - low (历史 seed / 过期) × 0.4
3. **Category 封顶 ±25**：同一 category 内所有规则 delta 之和被 clamp 到 `[-25, +25]`，避免同一风险被多条规则重复奖励（如棕榈油库存可能同时触发 3 条规则）
4. `raw_score = Σ category_capped_deltas` ；`final_score = clamp(raw_score, 0, 100)`
5. 等级映射（`config.yaml::risk_levels`）：
   - 0-30 🟢 绿色（无明显利多）
   - 31-50 🟡 黄色（局部扰动）
   - 51-70 🟠 橙色（多项指标偏多）
   - 71-85 🔴 红色（强供需冲击）
   - 86-100 🟣 紫色（极端行情风险）
6. 与昨日 / 上周分数对比 → `score_change_1d`, `score_change_7d`
7. 与昨日触发规则集合 diff → **变化来源**（added / removed / persistent rule ids），在报告 "较昨日变化来源" 章节展示
8. 等级与昨日不同 → **等级穿越** (regime change)，单独写入报告 + 触发预警

**置信度分数**：每个品种在报告总览表还会显示一个 `0-100` 的整体置信度（high=100, medium=70, low=30 取均值）。

**分类权重**（`config.yaml::weights`）v1 仅用于报告分类展示与 category cap 上限；不直接缩放分数。
计划在 v2 切换到 `weighted_sum × scale` 模式（待充分回测后）。

---

## 价格确认模块

风险雷达不仅看基本面，还要看**市场是否正在 price in**。价格确认是独立维度，**不参与 `final_score` 计算**，但融入结论文字。

### 信号配置（`scoring.PRICE_SIGNALS`）

| 品种 | 价格信号 | 权重 | 说明 |
|---|---|---:|---|
| 白糖 | ICE 11 号原糖 5日变化 | 2.0 | 国际定价 |
| | 伦敦 5 号白糖 5日变化 | 1.5 | |
| | USD/BRL 5日变化 | 1.0 (invert) | 雷亚尔贬值利空国际糖价 |
| 棕榈油 | BMD 棕榈油 5日变化 | 2.0 | 马来交易所主力 |
| | BMD 近远月价差 5日变化 | 1.0 | 现货紧张度 |
| | 生柴利润 | 0.8 | 替代品需求 |
| 橡胶 | 上期所 RU 5日变化 | 2.0 | 国内定价 |
| | INE 20号胶 5日变化 | 1.5 | 国际定价 |
| | 现货升贴水 | 1.0 | 现货供需 |

### 状态分类

加权方向得分 `pct = Σ(weight × {+1,-1,0}) / Σ weight`：

**基本面有方向时（final_score ≥ 31）**：

| 状态 | 条件 | 文字 |
|---|---|---|
| `confirmed` | pct ≥ 0.5 | 价格已确认基本面方向 |
| `partial` | 0 < pct < 0.5 | 价格部分确认基本面 |
| `weak` | -0.5 < pct ≤ 0 | 价格确认偏弱，需要继续验证 |
| `diverging` | pct ≤ -0.5 | 价格与基本面背离，持续性存疑 |

**基本面中性时（final_score < 31）**：

| 状态 | 条件 | 文字 |
|---|---|---|
| `price_leading` | \|pct\| ≥ 0.5 | 价格领先偏多/偏空，但基本面尚未确认 |
| `price_watch` | 0.2 ≤ \|pct\| < 0.5 | 价格出现微弱倾向，建议持续观察 |
| `neutral` | \|pct\| < 0.2 | 基本面与价格均中性 |
| `no_data` | 没有任何价格信号 | 缺少价格数据，确认状态未知 |

**为什么区分 confirmed / price_leading**：风险雷达不只是"基本面确认"，也要捕获"价格先行而基本面尚未发生"的早期信号。
之前版本会把"绿色 + 价格全偏多"误标为 neutral，完全掩盖了市场已在 price-in 的预期。

**置信度加权**：v3 的 weighted_pct 是 `Σ(weight × confidence_mult × side) / Σ(weight × confidence_mult)`。
所以全 manual medium 信号的 confirmed 强度低于全 yfinance high。报告里有 **价格确认置信度** 字段单独展示。

报告里有专门的 **"价格确认"** 章节，列出每个信号的值/方向/权重/置信度。frontmatter 也含 `{commodity}_price_confirmation` 字段，可用 Dataview 筛选。

---

## 预期差与季节性基准

绝对阈值规则（如"印度产量下调 >100 万吨 +15"）容易在数据平稳时反复触发噪音。
v2 加入两套**相对基准**规则，与绝对阈值并存（category cap 抑制重复加分）。

### 预期差（vs 市场预期）

为关键月报指标加 `_expected` 字段（彭博/路透/USDA 预测均值）：

| 字段 | _expected 字段 | 触发阈值 |
|---|---|---|
| `mpob_end_stock_mt` | `mpob_end_stock_mt_expected` | ±5% |
| `mpob_cpo_production_mt` | `mpob_cpo_production_mt_expected` | ±5% |
| `mpob_export_mt` | `mpob_export_mt_expected` | ±5% |
| `india_sugar_production_mt` | `india_sugar_production_mt_expected` | ±5% |
| `thailand_sugar_production_mt` | `thailand_sugar_production_mt_expected` | ±5% |
| `brazil_sugar_production_mt` | `brazil_sugar_production_mt_expected` | ±5% |

规则措辞：`马来库存低于市场预期 5.0%` / `印度糖产量高于市场预期 6.2%`。

### 季节性基准（vs 5 年同月/同周均值）

为强季节性指标加 `_5y_avg_*` 字段：

| 字段 | _5y_avg 字段 | 触发阈值 |
|---|---|---|
| `mpob_end_stock_mt` | `mpob_end_stock_5y_avg_mt` | ±10-15% |
| `mpob_export_mt` | `mpob_export_5y_avg_mt` | ±10% |
| `india_palm_import_mt + china_palm_import_mt` | 同名 5y avg | ±10% |
| `qingdao_bonded_stock_kt` | `qingdao_bonded_stock_5y_avg_kt` | ±10-15% |
| `china_semi/full_steel_tire_operating_rate_pct` | 同名 5y avg | ±3pp |

规则措辞：`青岛库存 vs 5年同月 -16.7%（偏紧）` / `轮胎开工 vs 5年同期 -6.5pp（弱于季节性）`。

**为什么并存而非替换**：v1 绝对阈值仍有价值（如"印度糖出口禁令 +15"是政策事件，不是连续变量）。预期差和季节性更适合 MPOB 库存这种连续变量。category cap 自动抑制同 category 的过度叠加。

---

## Monte Carlo 回测

由于没有真实"未来价格 ground truth"做监督，我们用 **机制性回测**：
基于 `manual_inputs.yaml` 的 baseline 加噪声生成 N 个随机 snapshot，跑评分体系，统计：

- 分数分布（mean/median/P10/P25/.../P90）
- 等级分布（绿/黄/橙/红/紫）
- 每条规则的触发率
- 每个 category 的贡献分布
- 价格确认状态分布

### 命令

```bash
python main.py backtest                              # 三品种各 1000 次
python main.py backtest --commodity palm             # 仅棕榈油
python main.py backtest --iterations 5000            # 更大样本
python main.py backtest --noise 0.4                  # 更宽噪声分布
python main.py backtest --seed 123                   # 复现实验
```

输出到 `reports/backtest_<commodity>_<date>.md`。

### 自动校准建议

报告末尾会列出问题规则：

```
- `palm.mpob.export_up_stock_down` 触发率 100% — 阈值可能太松
- `palm.brent.sustained_up` 触发率 0.1% — 阈值可能太严
```

**已用回测调过的规则**（实际改进）：

| Rule | 之前 | 之后 | 原因 |
|---|---|---|---|
| `palm.mpob.export_up_stock_down` | export>0 AND stock<0 | export≥3% AND stock≤-3% | 100% → 47% |
| `palm.import_recovery` | china≥5% OR india≥5% | china≥5% AND india≥5% | 92% → ~30% |
| `sugar.brazil.crush_yoy_down` | yoy<0 | yoy≤-1% | 100% → 80% |
| `sugar.eu.beet_area_down` | <0 | ≤-1% | 100% → 91% |
| `rubber.china.tire_op_up` | semi>0 AND full>0 | semi≥0.5 AND full≥0.5 | 100% → 97% |
| `rubber.china.tire_export_yoy_up` | yoy>0 | yoy≥3% | 100% → 97% |
| `rubber.inv.qingdao_down` | <0 | ≤-1.5% | 100% → 94% |
| 等等… | | | |

剩下的高触发率（80-97%）反映**当前 baseline 本身就处于"偏多"状态**（Niño 1.0、印度降雨偏少、青岛库存下降中），不是规则缺陷。
真实的阈值校准需要真实数据跑 30+ 天后再做。

### 整数变量特殊处理

`*_consecutive_*_days` 这类离散计数字段用 **Poisson(λ=baseline)** 采样，而非高斯噪声 — 否则"连续上涨 3 日"会被推到不合理的浮点数。

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
