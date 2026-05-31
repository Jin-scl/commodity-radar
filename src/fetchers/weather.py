"""区域天气 fetcher —— v1 全部走 manual_inputs.yaml 中各品种的天气字段。

v2 可接入 NOAA CPC 月度降雨距平、CMA 等。
"""
from __future__ import annotations

from src.fetchers.base import fetcher
from src.storage.database import Database


@fetcher("weather", manual_section=None, commodity="all")
def fetch_weather(db: Database) -> list[dict]:
    """v1：无实际抓取；返回空触发 fallback。weather 字段已散落在
    sugar/palm/rubber 各自 section 中，由对应 fetcher 拉取。
    """
    raise NotImplementedError("weather v1 全部走品种 fetcher")
