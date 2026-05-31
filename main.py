"""commodity_radar CLI 入口。

子命令：
  fetch     运行所有 fetcher（带 fallback），把指标写入 SQLite
  score     从 SQLite 取最新指标，跑规则评分，写入 scores 表
  report    生成 Markdown 日报到 reports/YYYY-MM-DD_daily_report.md
  run-all   fetch -> score -> report -> alert（推荐 cron 使用）
  seed      注入过去 7 天的模拟数据（首次使用前跑一次，让 1日/7日变化有意义）

示例：
  python main.py seed
  python main.py run-all
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 允许 `python main.py` 直接运行（添加项目根到 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.alerts.dispatcher import dispatch, evaluate_alerts
from src.fetchers.orchestrator import run_all_fetchers
from src.indicators.scoring import evaluate_all, persist_scores
from src.reports.daily_report import build_snapshots, generate
from src.storage.database import today_str
from src.utils import (
    get_database, get_logger, load_manual_inputs,
    manual_section_to_indicators,
)


def cmd_fetch(args):
    logger = get_logger()
    db = get_database()
    summary = run_all_fetchers(db)
    logger.info("fetch summary: %s", summary)
    return 0


def cmd_score(args):
    logger = get_logger()
    db = get_database()
    from src.utils import load_config
    cfg = load_config()
    commodities = cfg["commodities"]
    _, snaps = build_snapshots(db, commodities)
    results = evaluate_all(snaps, db=db, score_date=args.date, config=cfg)
    persist_scores(results, db)
    for c, r in results.items():
        logger.info("score %s: %d (%s), 1d=%s, 7d=%s", c, r["final_score"],
                    r["risk_level_label"], r["score_change_1d"],
                    r["score_change_7d"])
    return 0


def cmd_report(args):
    db = get_database()
    alerts = []
    if args.with_alerts:
        from src.utils import load_config
        cfg = load_config()
        commodities = cfg["commodities"]
        _, snaps = build_snapshots(db, commodities)
        results = evaluate_all(snaps, db=db, score_date=args.date, config=cfg)
        alerts = evaluate_alerts(results, db, cfg)
    path = generate(score_date=args.date, alerts=alerts)
    print(f"Report: {path}")
    return 0


def cmd_run_all(args):
    logger = get_logger()
    db = get_database()
    from src.utils import load_config

    logger.info("=== run-all start ===")

    # 1) fetch
    summary = run_all_fetchers(db)
    logger.info("fetch summary: %s", summary)

    # 2) score（在 build_snapshots 之后；只算一次）
    cfg = load_config()
    commodities = cfg["commodities"]
    _, snaps = build_snapshots(db, commodities)
    results = evaluate_all(snaps, db=db, score_date=args.date, config=cfg)

    # 3) alerts（评分完成后，对 events 表 + scores 共同判断）
    alerts = evaluate_alerts(results, db, cfg)
    dispatch_result = dispatch(alerts, args.date or today_str())
    logger.info("alerts dispatched: %s", dispatch_result)

    # 4) generate report（让 generate 内部处理 persist + alerts 分组，
    #    并复用上面算好的 results，避免重算）
    path = generate(score_date=args.date, persist=True, db=db,
                    alerts=alerts, precomputed_results=results)
    logger.info("=== run-all done -> %s ===", path)
    print(f"Report: {path}")
    return 0


def cmd_seed(args):
    """注入过去 N 天历史 indicators + scores，让 1日/7日变化有真实数字。
    使用 manual_inputs.yaml 当前值 + 小幅随机扰动作为历史。
    """
    logger = get_logger()
    db = get_database()
    from src.utils import load_config
    cfg = load_config()
    days = args.days
    today = datetime.now().date()
    random.seed(20260531)  # 可复现

    manual = load_manual_inputs()
    # 注意：seed 不回填 common/market —— 这两段由真实 fetcher 当日抓取，
    # 失败时 base.fetcher 自动 fallback 到 manual_inputs.yaml 当日数据，
    # 不需要 seed 历史（否则历史 timestamp 可能压过真实抓取结果）
    sections = {
        "sugar": "sugar", "palm": "palm", "rubber": "rubber",
    }

    inserted = 0
    for n in range(days, 0, -1):  # days..1，保留 today 留给 fetch
        date = (today - timedelta(days=n)).strftime("%Y-%m-%d")
        for commodity, sec in sections.items():
            inds = manual_section_to_indicators(
                commodity, manual.get(sec, {}), default_timestamp=date)
            # 给数值型字段加一点扰动（±5%）
            for ind in inds:
                if ind.get("value_num") is not None:
                    perturb = 1 + random.uniform(-0.05, 0.05)
                    ind["value_num"] = round(ind["value_num"] * perturb, 4)
                ind["timestamp"] = date
                ind["confidence"] = "low"  # 历史模拟数据
                ind["notes"] = (ind.get("notes") or "") + " [seeded]"
                db.save_indicator(ind)
                inserted += 1
        # 跑一次评分写历史 scores
        _, snaps = build_snapshots(db, cfg["commodities"])
        results = evaluate_all(snaps, db=db, score_date=date, config=cfg)
        persist_scores(results, db)
    logger.info("seeded %d indicator rows across %d days", inserted, days)
    print(f"Seeded {days} days history (~{inserted} indicator rows).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="commodity_radar",
        description="基本面风险雷达 — 白糖 / 棕榈油 / 天然橡胶",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("fetch", help="运行所有 fetcher")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("score", help="跑规则评分")
    sp.add_argument("--date", help="评分日期 YYYY-MM-DD（默认今天）")
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser("report", help="生成 Markdown 报告")
    sp.add_argument("--date", help="报告日期 YYYY-MM-DD（默认今天）")
    sp.add_argument("--with-alerts", action="store_true",
                    help="报告中包含预警章节")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("run-all", help="fetch -> score -> report -> alert")
    sp.add_argument("--date", help="日期 YYYY-MM-DD（默认今天）")
    sp.set_defaults(func=cmd_run_all)

    sp = sub.add_parser("seed", help="注入历史模拟数据")
    sp.add_argument("--days", type=int, default=8,
                    help="回填多少天（默认 8 天，覆盖 7 日变化）")
    sp.set_defaults(func=cmd_seed)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
