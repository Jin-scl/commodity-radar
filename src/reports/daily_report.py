"""每日报告编排：从 SQLite 读最新数据 -> 评分 -> 渲染 -> 写文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.indicators.scoring import evaluate_all, persist_scores
from src.reports.markdown_report import render_report, write_report
from src.storage.database import Database, today_str
from src.utils import (
    get_database, get_logger, indicators_to_snapshot, load_config,
    resolve_path,
)


def _partition_alerts_by_commodity(
        alerts: list[dict], commodities: list[str]) -> dict[str, list[dict]]:
    """每个品种只持有 commodity == 自己 或 commodity in ('all','common') 的预警。"""
    out: dict[str, list[dict]] = {c: [] for c in commodities}
    for a in alerts:
        c = a.get("commodity", "all")
        if c in out:
            out[c].append(a)
        elif c in ("all", "common"):
            for k in out:
                out[k].append(a)
    return out


def build_snapshots(db: Database, commodities: list[str],
                    as_of_date: Optional[str] = None) -> tuple[
        dict[str, list[dict]], dict[str, dict]]:
    """对每个 commodity：取最新 indicators + common/market 公共指标。

    as_of_date: 只看 timestamp <= 该日期；为 None 时取当前最新。
    seed 数据始终排除（保证不污染最新快照）。
    """
    inds_by_c: dict[str, list[dict]] = {}
    snaps_by_c: dict[str, dict] = {}
    common_inds = db.get_latest_indicators(commodity="common",
                                           as_of_date=as_of_date)
    market_inds = db.get_latest_indicators(commodity="market",
                                           as_of_date=as_of_date)
    common_snap = indicators_to_snapshot(common_inds + market_inds)
    for c in commodities:
        own = db.get_latest_indicators(commodity=c, as_of_date=as_of_date)
        all_inds = own + common_inds + market_inds
        inds_by_c[c] = all_inds
        snap = indicators_to_snapshot(own)
        for k, v in common_snap.items():
            snap.setdefault(k, v)
        snaps_by_c[c] = snap
    return inds_by_c, snaps_by_c


def generate(score_date: Optional[str] = None,
             persist: bool = True,
             db: Optional[Database] = None,
             alerts: Optional[list[dict]] = None,
             precomputed_results: Optional[dict[str, dict]] = None) -> Path:
    """主入口：生成今日报告并返回主 Markdown 路径（本地 reports/ 下的路径）。

    若调用方已经算好评分（如 cmd_run_all），传 `precomputed_results` 避免重算。
    Obsidian vault 副本由 write_report 内部根据 config 自动写入。
    """
    logger = get_logger()
    cfg = load_config()
    db = db or get_database()
    score_date = score_date or today_str()
    commodities = cfg["commodities"]

    inds_by_c, snaps_by_c = build_snapshots(db, commodities,
                                            as_of_date=score_date)
    logger.info("Loaded snapshots for: %s (as_of=%s)",
                ", ".join(commodities), score_date)

    if precomputed_results is not None:
        results = precomputed_results
    else:
        results = evaluate_all(snaps_by_c, db=db, score_date=score_date,
                               config=cfg)
    scores_list = [results[c] for c in commodities]

    if persist:
        # 修复 Bug B：alerts 按 commodity 分组（含 'all' / 'common' 类全局事件）
        per_c_alerts = _partition_alerts_by_commodity(alerts or [], commodities)
        persist_scores(results, db, alerts=per_c_alerts)

    md = render_report(
        score_date=score_date,
        scores=scores_list,
        indicators_by_commodity=inds_by_c,
        snapshots_by_commodity=snaps_by_c,
        alerts=alerts or [],
        include_frontmatter=cfg.get("report", {}).get("include_frontmatter", True),
    )

    obs_cfg = cfg.get("obsidian", {}) or {}
    obsidian_dir = None
    if obs_cfg.get("enabled"):
        vault = obs_cfg.get("vault_path")
        subfolder = obs_cfg.get("subfolder") or ""
        if vault:
            obsidian_dir = Path(vault).expanduser() / subfolder if subfolder \
                else Path(vault).expanduser()

    out_paths = write_report(
        md,
        resolve_path(cfg["paths"]["reports"]),
        score_date,
        obsidian_dir=obsidian_dir,
        also_create_index=bool(obs_cfg.get("create_index")),
    )
    for p in out_paths:
        logger.info("Report written: %s", p)
    return out_paths[0]  # 返回本地路径作为主路径
