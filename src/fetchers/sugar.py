"""白糖 fetcher —— v1 编排型：从 manual_inputs.yaml::sugar 加载所有字段，
后续可在此覆盖部分真实抓取（如 NY 11 号原糖、ISMA 月报）。
"""
from __future__ import annotations

from src.fetchers.base import fetcher, load_manual_for
from src.storage.database import Database


@fetcher("sugar", manual_section="sugar", commodity="sugar")
def fetch_sugar(db: Database) -> list[dict]:
    # v1：直接返回 manual section（fetcher 装饰器会把它们写入 DB）
    return load_manual_for("sugar", "sugar")
