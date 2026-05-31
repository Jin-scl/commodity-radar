"""天然橡胶 fetcher —— v1 编排型：ANRPC / 轮胎开工率 / 青岛库存 从 manual。

v2 可接入 akshare（青岛保税库存、上期所库存、轮胎企业开工率）+ 期货价格。
"""
from __future__ import annotations

from src.fetchers.base import fetcher, load_manual_for
from src.storage.database import Database


@fetcher("rubber", manual_section="rubber", commodity="rubber")
def fetch_rubber(db: Database) -> list[dict]:
    return load_manual_for("rubber", "rubber")
