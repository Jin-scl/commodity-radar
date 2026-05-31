"""新闻 RSS fetcher —— 抓取并按关键词匹配，写入 events 表。

v1 用 USDA / Reuters 几个公共 RSS。匹配 config.yaml::alerts.critical_keywords
的事件会被标记 severity=critical。

manual_events 段也会被一起注入 events 表（首次抓取时）。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import feedparser

from src.fetchers.base import fetcher
from src.storage.database import Database
from src.utils import get_logger, load_config, load_manual_inputs

RSS_FEEDS = [
    "https://www.fas.usda.gov/data/feed",   # USDA Foreign Agricultural Service
    # 添加更多 RSS 时需要确保它们是公开稳定的源
]


def _matches_keyword(text: str, keywords: list[str]) -> str | None:
    low = text.lower()
    for kw in keywords:
        if kw.lower() in low:
            return kw
    return None


@fetcher("news", manual_section="manual_events", commodity="all")
def fetch_news(db: Database) -> list[dict]:
    """注意：这个 fetcher 主要写 events 表（而非 indicators）。
    返回一个"哨兵 indicator"用于满足装饰器的非空判定 + 记录抓取状态。
    """
    logger = get_logger()
    cfg = load_config()
    keywords = cfg.get("alerts", {}).get("critical_keywords", [])

    new_events = 0

    # 1) 先注入 manual_events（每次都会幂等检查：相同 message+timestamp 跳过）
    manual = load_manual_inputs()
    for ev in manual.get("manual_events", []) or []:
        msg = ev.get("message", "")
        ts = ev.get("timestamp") or datetime.now().strftime("%Y-%m-%d")
        commodity = ev.get("commodity", "all")
        severity = ev.get("severity", "info")
        kw_hit = _matches_keyword(msg, keywords)
        if kw_hit:
            severity = "critical"
        # 简单查重：最近 7 天同 message 不重复
        recent = db.get_recent_events(hours=24 * 7, commodity=commodity)
        if any(e["message"] == msg for e in recent):
            continue
        db.save_event(commodity, ev.get("type", "manual"), msg, severity,
                      source="manual_inputs.yaml")
        new_events += 1

    # 2) RSS 抓取
    fetched_rss = 0
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "commodity_radar/1.0"})
            for entry in (feed.entries or [])[:30]:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                text = f"{title} {summary}"
                kw_hit = _matches_keyword(text, keywords)
                if not kw_hit:
                    continue
                # 判断所属品种
                commodity = "all"
                low = text.lower()
                if any(s in low for s in ("sugar", "白糖", "甘蔗", "印度糖")):
                    commodity = "sugar"
                elif any(s in low for s in ("palm", "棕榈", "mpob", "cpo")):
                    commodity = "palm"
                elif any(s in low for s in ("rubber", "天然胶", "anrpc", "天胶")):
                    commodity = "rubber"
                recent = db.get_recent_events(hours=24 * 7, commodity=commodity)
                if any(e["message"].strip() == title.strip() for e in recent):
                    continue
                db.save_event(commodity, "news", title, "critical",
                              source=f"RSS {url}")
                new_events += 1
                fetched_rss += 1
        except Exception as e:
            logger.warning("RSS %s failed: %s", url, e)

    logger.info("news: manual=%d, rss=%d new events", new_events - fetched_rss, fetched_rss)

    # 返回一个哨兵 indicator 让 base.fetcher 不视为失败
    return [{
        "commodity": "common",
        "name": "news_events_count_today",
        "value_num": float(new_events),
        "unit": "count",
        "source": "news fetcher",
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "fetched_at": None,
        "confidence": "high",
        "is_manual": False,
        "notes": "今日新增 events 数（含 manual_events 注入）",
    }]
