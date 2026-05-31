"""棕榈油 fetcher —— v1 编排型：MPOB / 印尼数据从 manual_inputs.yaml::palm。

v2 可接入 MPOB 月报 HTML 抓取 + akshare 棕榈油期货。
"""
from __future__ import annotations

from src.fetchers.base import fetcher, load_manual_for
from src.storage.database import Database


@fetcher("palm", manual_section="palm", commodity="palm")
def fetch_palm(db: Database) -> list[dict]:
    return load_manual_for("palm", "palm")
