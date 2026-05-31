"""通用工具：配置加载、日志、路径解析。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: str | Path | None = None) -> dict:
    path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def load_manual_inputs(path: str | Path | None = None) -> dict:
    p = Path(path) if path else PROJECT_ROOT / "manual_inputs.yaml"
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_path(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


_LOGGER_INITIALIZED = False


def get_logger(name: str = "commodity_radar") -> logging.Logger:
    global _LOGGER_INITIALIZED
    logger = logging.getLogger(name)
    if _LOGGER_INITIALIZED:
        return logger

    cfg = load_config()
    level_name = os.environ.get("LOG_LEVEL") or "INFO"
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_path = resolve_path(cfg.get("paths", {}).get(
        "log_file", "data/raw/commodity_radar.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.propagate = False
    _LOGGER_INITIALIZED = True
    return logger


def get_database():
    """便捷工厂：根据 config.yaml 实例化 Database。"""
    from src.storage.database import Database
    cfg = load_config()
    return Database(resolve_path(cfg["paths"]["database"]))


def deep_get(d: dict, keys: str, default: Any = None) -> Any:
    """deep_get(d, 'a.b.c') 等价 d.get('a', {}).get('b', {}).get('c')"""
    cur: Any = d
    for k in keys.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def manual_entry_to_indicator(commodity: str, name: str, entry: Any,
                              default_timestamp: str | None = None) -> dict:
    """把 manual_inputs.yaml 的一条记录转成 indicator dict。
    支持两种格式：
      shorthand: name: 3.5            -> {value: 3.5}
      full     : name: {value, unit, timestamp, source, notes, confidence}
    """
    if not isinstance(entry, dict):
        entry = {"value": entry}
    val = entry.get("value")
    value_num: float | None = None
    value_text: str | None = None
    if isinstance(val, bool):
        value_text = "true" if val else "false"
    elif isinstance(val, (int, float)):
        value_num = float(val)
    elif val is None:
        pass
    else:
        value_text = str(val)
    return {
        "commodity": commodity,
        "name": name,
        "value_num": value_num,
        "value_text": value_text,
        "unit": entry.get("unit"),
        "source": entry.get("source", "manual"),
        "timestamp": entry.get("timestamp", default_timestamp),
        "fetched_at": None,  # database 会填
        "confidence": entry.get("confidence", "medium"),
        "is_manual": True,
        "notes": entry.get("notes"),
    }


def manual_section_to_indicators(commodity: str, section: dict,
                                 default_timestamp: str | None = None
                                 ) -> list[dict]:
    """把 manual_inputs.yaml 中某一节（如 sugar / common / market）转成 indicator 列表。"""
    out: list[dict] = []
    if not isinstance(section, dict):
        return out
    for name, entry in section.items():
        out.append(manual_entry_to_indicator(commodity, name, entry,
                                             default_timestamp))
    return out


def indicators_to_snapshot(indicators: Iterable[dict]) -> dict[str, dict]:
    """把 indicator list 转成 {name: {value, unit, source, ...}} 扁平字典，
    便于 rules.py 直接按字段名取值。
    """
    snap: dict[str, dict] = {}
    for ind in indicators:
        name = ind.get("name")
        if not name:
            continue
        if ind.get("value_num") is not None:
            value = ind["value_num"]
        elif ind.get("value_text") is not None:
            value = ind["value_text"]
        else:
            value = None
        snap[name] = {
            "value": value,
            "unit": ind.get("unit"),
            "source": ind.get("source"),
            "timestamp": ind.get("timestamp"),
            "confidence": ind.get("confidence"),
            "is_manual": bool(ind.get("is_manual")),
            "notes": ind.get("notes"),
        }
    return snap


