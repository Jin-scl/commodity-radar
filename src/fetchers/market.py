"""市场价格 fetcher —— yfinance；失败 fallback 到 manual_inputs.yaml::market。

注意：yfinance 在国内 VPS 可能受限；任何抓取失败都不影响后续流程。
"""
from __future__ import annotations

from datetime import datetime

from src.fetchers.base import fetcher
from src.storage.database import Database, now_iso
from src.utils import get_logger

# (我们的 indicator name -> yfinance ticker)
TICKERS = {
    "brent_price_usd": "BZ=F",        # Brent crude futures
    "soybean_oil_price_usd": "ZL=F",  # CBOT Soybean Oil
    # 棕榈油 / 橡胶期货 yfinance 覆盖不稳，缺失时 fallback manual
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
    try:
        import yfinance as yf  # 延迟导入避免无网时崩溃
    except ImportError as e:
        raise RuntimeError(f"yfinance not available: {e}")

    out: list[dict] = []
    fetched_at = now_iso()

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
        except Exception as e:
            logger.warning("yfinance %s (%s) failed: %s", name, ticker, e)

    if not out:
        raise RuntimeError("yfinance fetched 0 series")
    return out
