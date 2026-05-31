"""统一调度入口：根据 config.fetchers 开关跑各 fetcher。"""
from __future__ import annotations

from src.fetchers import enso, market, news, palm, rubber, sugar
from src.storage.database import Database
from src.utils import get_logger, load_config

FETCHERS = {
    "enso": enso.fetch_enso,
    "market": market.fetch_market,
    "news": news.fetch_news,
    "sugar": sugar.fetch_sugar,
    "palm": palm.fetch_palm,
    "rubber": rubber.fetch_rubber,
}


def run_all_fetchers(db: Database) -> dict[str, int]:
    """按 config 开关执行所有 fetcher，返回 {fetcher_name: records_count}。
    每个 fetcher 内部已经做了 try/except + fallback，这里不再包一层。
    """
    cfg = load_config()
    enabled = cfg.get("fetchers", {})
    log = get_logger()
    out: dict[str, int] = {}
    for name, fn in FETCHERS.items():
        if not enabled.get(name, True):
            log.info("fetcher.%s disabled by config, skip", name)
            continue
        try:
            inds = fn(db)
        except Exception as e:
            # 二级兜底：理论上 base.fetcher 会兜，这里再保一次保险
            log.error("fetcher.%s uncaught: %s", name, e)
            inds = []
        out[name] = len(inds) if inds else 0
    return out
