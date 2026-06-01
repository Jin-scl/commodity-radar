"""市场价格 fetcher —— yfinance 抓取真实数据 + manual_inputs.yaml::market 补齐。

设计：
- 先按 TICKERS 跑 yfinance（成功的字段标 confidence=high, is_manual=False）
- 然后读 manual_inputs.yaml::market，**只补齐 yfinance 未抓到**的字段
- 同名字段以 yfinance 优先；manual 部分标 is_manual=True

这样无论 yfinance 全成功、部分成功、全失败，菜油/葵油/丁二烯/合成胶等
manual-only 字段都不会"静默丢失"。
"""
from __future__ import annotations

from datetime import datetime

from src.fetchers.base import fetcher
from src.storage.database import Database, now_iso
from src.utils import (
    get_logger, load_manual_inputs, manual_section_to_indicators,
)

# (我们的 indicator name -> yfinance ticker)
TICKERS = {
    "brent_price_usd": "BZ=F",        # Brent crude futures
    "soybean_oil_price_usd": "ZL=F",  # CBOT Soybean Oil
    # 棕榈油 / 橡胶期货 yfinance 覆盖不稳，统一交给 manual 补齐
}


def _consecutive_up_days(closes: list[float]) -> int:
    """从最新往前数连续上涨天数。"""
    if not closes or len(closes) < 2:
        return 0
    n = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            n += 1
        else:
            break
    return n


@fetcher("market", manual_section="market", commodity="market")
def fetch_market(db: Database) -> list[dict]:
    logger = get_logger()
    out: list[dict] = []
    fetched_at = now_iso()
    yf_names_filled: set[str] = set()

    # 1) 真实抓取（缺 yfinance 模块也不算致命，下面 manual 会接管）
    try:
        import yfinance as yf  # 延迟导入避免无网时崩溃
    except ImportError as e:
        logger.warning("yfinance import failed: %s — 将完全使用 manual::market", e)
        yf = None

    if yf is not None:
        for name, ticker in TICKERS.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="10d", interval="1d")
                if hist is None or hist.empty:
                    logger.warning("yfinance empty for %s (%s)", name, ticker)
                    continue
                closes = hist["Close"].dropna().tolist()
                last_price = float(closes[-1])
                last_date = hist.index[-1].strftime("%Y-%m-%d")
                out.append({
                    "commodity": "market", "name": name,
                    "value_num": last_price, "unit": "USD",
                    "source": f"yfinance {ticker}", "timestamp": last_date,
                    "fetched_at": fetched_at,
                    "confidence": "high", "is_manual": False,
                })
                yf_names_filled.add(name)
                # 推导：连续上涨天数
                derived_name = name.replace("_price_usd", "_consecutive_up_days")
                up = _consecutive_up_days(closes)
                out.append({
                    "commodity": "market", "name": derived_name,
                    "value_num": float(up), "unit": "days",
                    "source": f"yfinance {ticker} (derived)",
                    "timestamp": last_date, "fetched_at": fetched_at,
                    "confidence": "high", "is_manual": False,
                })
                yf_names_filled.add(derived_name)
            except Exception as e:
                logger.warning("yfinance %s (%s) failed: %s", name, ticker, e)

    # 2) 用 manual::market 补齐 yfinance 未填的字段
    today = datetime.now().strftime("%Y-%m-%d")
    manual = load_manual_inputs()
    manual_inds = manual_section_to_indicators(
        "market", manual.get("market", {}), default_timestamp=today)
    added_from_manual = 0
    for ind in manual_inds:
        if ind["name"] in yf_names_filled:
            continue
        ind["confidence"] = ind.get("confidence") or "medium"
        ind["is_manual"] = True
        out.append(ind)
        added_from_manual += 1

    logger.info("market fetch: %d from yfinance + %d from manual",
                len(yf_names_filled), added_from_manual)
    if not out:
        # 极端情况：yfinance 失败 + manual 也空，让装饰器记录 failed
        raise RuntimeError("market fetched 0 series (yfinance + manual both empty)")
    return out
