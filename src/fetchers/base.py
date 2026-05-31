"""Fetcher 基类与公共工具。

设计要点：
- 所有 fetcher 用 @fetcher 装饰，统一异常处理 + fetch_log + 计时
- fallback_to_manual() 在抓取失败时从 manual_inputs.yaml 取出对应 section
"""
from __future__ import annotations

import functools
import time
from typing import Callable

from src.storage.database import Database
from src.utils import (
    get_logger, load_manual_inputs, manual_section_to_indicators,
)


def fetcher(name: str, manual_section: str | None = None,
            commodity: str = ""):
    """装饰 fetch 函数：捕获异常，失败自动 fallback 到 manual_inputs.yaml。

    被装饰函数签名：fn(db: Database) -> list[indicator dict]
    返回的 indicator 会被写入 db；失败时改用 manual 段。
    """
    def decorator(fn: Callable[[Database], list[dict]]):
        @functools.wraps(fn)
        def wrapper(db: Database):
            logger = get_logger()
            start = time.time()
            indicators: list[dict] = []
            status = "success"
            error = None
            try:
                indicators = fn(db) or []
                if not indicators:
                    raise RuntimeError("fetcher returned empty result")
                logger.info("fetcher.%s ok: %d records", name, len(indicators))
            except Exception as e:
                status = "failed"
                error = f"{type(e).__name__}: {e}"
                logger.warning("fetcher.%s failed: %s — fallback to manual",
                               name, error)
                db.save_event(commodity or "all", "fetcher_error",
                              f"{name}: {error}", "warn", source=name)
                # fallback
                if manual_section:
                    from datetime import datetime as _dt
                    today = _dt.now().strftime("%Y-%m-%d")
                    manual = load_manual_inputs()
                    section = manual.get(manual_section, {})
                    indicators = manual_section_to_indicators(
                        commodity or manual_section, section,
                        default_timestamp=today,
                    )
                    # 强制 fallback 数据使用今天 timestamp，确保胜过任何历史 seed
                    for ind in indicators:
                        ind["timestamp"] = today
                        ind["notes"] = (ind.get("notes") or "") + " [fallback]"
                    logger.info("fetcher.%s fallback loaded %d manual records",
                                name, len(indicators))
            for ind in indicators:
                db.save_indicator(ind)
            duration_ms = int((time.time() - start) * 1000)
            db.log_fetch(name, status, len(indicators), error, duration_ms)
            return indicators
        return wrapper
    return decorator


def load_manual_for(section: str, commodity: str,
                    use_today_as_default: bool = True) -> list[dict]:
    """便捷工具：直接读 manual_inputs.yaml 某段并转 indicator。

    use_today_as_default=True（默认）：default_timestamp 用今天，避免
    snapshot_date 未更新导致历史 seed 数据反过来压过当日 fetch。
    字段自带 timestamp 的仍然以字段为准。
    """
    from datetime import datetime as _dt
    manual = load_manual_inputs()
    default_ts = _dt.now().strftime("%Y-%m-%d") if use_today_as_default \
        else manual.get("snapshot_date")
    return manual_section_to_indicators(
        commodity, manual.get(section, {}),
        default_timestamp=default_ts,
    )
