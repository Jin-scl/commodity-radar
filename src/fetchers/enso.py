"""ENSO fetcher —— 优先从 NOAA CPC 抓取，失败 fallback 到 manual_inputs.yaml::common。

数据源：
  https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for   (Niño 3.4 weekly, 1991-2020 base)
  https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

from src.fetchers.base import fetcher
from src.storage.database import Database, now_iso
from src.utils import get_logger

NINO34_URL = "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"
ONI_URL = "https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt"
TIMEOUT = 15


def _parse_nino34_weekly(text: str) -> tuple[float, str] | None:
    """NOAA 周度文件，最后一条非空数据行的第 5 列是 Niño 3.4 anomaly。"""
    lines = [ln for ln in text.splitlines() if ln.strip()
             and not ln.startswith("Week") and not ln.startswith("--")
             and re.search(r"\d", ln)]
    for ln in reversed(lines):
        parts = ln.split()
        if len(parts) >= 9:
            try:
                anom = float(parts[-1])
                date_str = parts[0]  # 形如 02MAY2025
                dt = datetime.strptime(date_str, "%d%b%Y")
                return anom, dt.strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                continue
    return None


def _parse_oni(text: str) -> tuple[float, str, int] | None:
    """ONI ascii 文件最后一行的 ANOM 列；同时统计连续 >+0.5 月数。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows = []
    for ln in lines[1:]:  # skip header
        parts = ln.split()
        if len(parts) >= 4:
            try:
                yr = int(parts[0]); mo = int(parts[1])
                anom = float(parts[-1])
                rows.append((yr, mo, anom))
            except ValueError:
                continue
    if not rows:
        return None
    latest_yr, latest_mo, latest_anom = rows[-1]
    streak = 0
    for _, _, a in reversed(rows):
        if a > 0.5:
            streak += 1
        else:
            break
    date_str = f"{latest_yr:04d}-{latest_mo:02d}-15"
    return latest_anom, date_str, streak


@fetcher("enso", manual_section="common", commodity="common")
def fetch_enso(db: Database) -> list[dict]:
    logger = get_logger()
    out: list[dict] = []
    fetched_at = now_iso()

    # Niño 3.4
    try:
        r = requests.get(NINO34_URL, timeout=TIMEOUT)
        r.raise_for_status()
        parsed = _parse_nino34_weekly(r.text)
        if parsed:
            anom, ts = parsed
            out.append({
                "commodity": "common", "name": "nino34",
                "value_num": anom, "unit": "°C",
                "source": "NOAA CPC weekly", "timestamp": ts,
                "fetched_at": fetched_at,
                "confidence": "high", "is_manual": False,
                "notes": "Nino 3.4 weekly anomaly (1991-2020 base)",
            })
    except Exception as e:
        logger.warning("NOAA Niño 3.4 fetch failed: %s", e)

    # ONI
    try:
        r = requests.get(ONI_URL, timeout=TIMEOUT)
        r.raise_for_status()
        parsed = _parse_oni(r.text)
        if parsed:
            anom, ts, streak = parsed
            out.append({
                "commodity": "common", "name": "oni",
                "value_num": anom, "unit": "°C",
                "source": "NOAA ONI ascii", "timestamp": ts,
                "fetched_at": fetched_at, "confidence": "high",
                "is_manual": False, "notes": "ONI 月度值",
            })
            out.append({
                "commodity": "common",
                "name": "oni_consecutive_months_above_0_5",
                "value_num": float(streak), "unit": "months",
                "source": "NOAA ONI ascii (derived)",
                "timestamp": ts, "fetched_at": fetched_at,
                "confidence": "high", "is_manual": False,
            })
    except Exception as e:
        logger.warning("NOAA ONI fetch failed: %s", e)

    if not out:
        # 让 @fetcher 装饰器走 fallback
        raise RuntimeError("All NOAA ENSO endpoints failed")
    return out
