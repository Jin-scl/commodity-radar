"""通用工具：配置加载、日志、路径解析。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable

import yaml
from dotenv import load_dotenv

# 在模块加载时就读取 .env，让任何 load_config 都能拿到环境变量
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env",
            override=False)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: str | Path | None = None) -> dict:
    """读取 config.yaml；少数字段支持环境变量覆盖（用于本地 .env）。

    支持的 env：
      OBSIDIAN_ENABLED=true|false
      OBSIDIAN_VAULT_PATH=/path/to/vault
      OBSIDIAN_SUBFOLDER=commodity_radar
    """
    path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    obs = cfg.setdefault("obsidian", {})
    env_enabled = os.environ.get("OBSIDIAN_ENABLED")
    if env_enabled is not None:
        obs["enabled"] = env_enabled.lower() in ("true", "1", "yes", "on")
    if os.environ.get("OBSIDIAN_VAULT_PATH"):
        obs["vault_path"] = os.environ["OBSIDIAN_VAULT_PATH"]
    if os.environ.get("OBSIDIAN_SUBFOLDER"):
        obs["subfolder"] = os.environ["OBSIDIAN_SUBFOLDER"]
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


def _freshness_hours_for(name: str, freshness_cfg: dict) -> float:
    """按 indicator 名前缀匹配 freshness 阈值；最长前缀优先。"""
    by_prefix = (freshness_cfg or {}).get("by_prefix", {}) or {}
    best_prefix = ""
    for p in by_prefix:
        if name.startswith(p) and len(p) > len(best_prefix):
            best_prefix = p
    if best_prefix:
        return float(by_prefix[best_prefix])
    return float((freshness_cfg or {}).get("default_hours", 168))


def effective_confidence(name: str, timestamp: str | None,
                         stated_confidence: str | None,
                         as_of_date: str | None = None,
                         freshness_cfg: dict | None = None) -> str:
    """按 freshness 自动降级 confidence。

    规则：
    - timestamp 缺失 → 用 stated_confidence
    - age <= freshness_hours        → 保持 stated_confidence
    - freshness < age <= 2*freshness → 至少降到 medium
    - age > 2*freshness             → 降到 low
    - age 解析失败 → 用 stated_confidence

    age 按 as_of_date（缺省今日）- timestamp 算。
    """
    stated = stated_confidence or "medium"
    if not timestamp:
        return stated
    from datetime import datetime as _dt
    try:
        # 兼容 "YYYY-MM-DD" 和 "YYYY-MM-DDT..." 两种
        ts = _dt.fromisoformat(timestamp.replace("Z", "+00:00")) \
            if "T" in timestamp else _dt.strptime(timestamp[:10], "%Y-%m-%d")
        ref = _dt.fromisoformat(as_of_date) if as_of_date and "T" in as_of_date \
            else _dt.strptime((as_of_date or _dt.now().strftime("%Y-%m-%d"))[:10],
                              "%Y-%m-%d")
    except (ValueError, TypeError):
        return stated
    # 都转成 naive datetime 比较（取日期级足够）
    ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
    ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
    age_hours = (ref_naive - ts_naive).total_seconds() / 3600.0
    if age_hours < 0:
        return stated  # 未来日期不降级
    hours = _freshness_hours_for(name, freshness_cfg or {})
    medium_ratio = float((freshness_cfg or {}).get("medium_at_ratio", 1.0))
    low_ratio = float((freshness_cfg or {}).get("low_at_ratio", 2.0))
    # 等级排序：high > medium > low
    rank = {"high": 3, "medium": 2, "low": 1}
    cap = "high"
    if age_hours > hours * low_ratio:
        cap = "low"
    elif age_hours > hours * medium_ratio:
        cap = "medium"
    # 取 stated 和 cap 中较低者
    if rank.get(stated, 2) <= rank.get(cap, 3):
        return stated
    return cap


def indicators_to_snapshot(indicators: Iterable[dict],
                           as_of_date: str | None = None,
                           freshness_cfg: dict | None = None) -> dict[str, dict]:
    """把 indicator list 转成 {name: {value, unit, source, confidence, ...}} 扁平字典。

    confidence 字段应用 effective_confidence：根据 timestamp + freshness_cfg
    自动降级（旧数据降为 medium / 过老降为 low）。
    """
    snap: dict[str, dict] = {}
    if freshness_cfg is None:
        try:
            freshness_cfg = load_config().get("freshness", {})
        except Exception:
            freshness_cfg = {}
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
        stated = ind.get("confidence")
        eff = effective_confidence(name, ind.get("timestamp"), stated,
                                   as_of_date=as_of_date,
                                   freshness_cfg=freshness_cfg)
        snap[name] = {
            "value": value,
            "unit": ind.get("unit"),
            "source": ind.get("source"),
            "timestamp": ind.get("timestamp"),
            "confidence": eff,
            "stated_confidence": stated,  # 保留原值供审计
            "is_manual": bool(ind.get("is_manual")),
            "notes": ind.get("notes"),
        }
    return snap


