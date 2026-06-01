"""预警调度器：根据评分结果 + events 表判断是否触发，分发到 Telegram/Email/Feishu。"""
from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

from src.alerts import email_alert, feishu, telegram
from src.storage.database import Database
from src.utils import get_logger, load_config

load_dotenv()

CHANNELS = [
    ("telegram", telegram.send),
    ("email", email_alert.send),
    ("feishu", feishu.send),
]


def evaluate_alerts(scores: dict[str, dict], db: Database,
                    config: Optional[dict] = None) -> list[dict]:
    """根据 scores + 最近 24h events 生成预警列表。
    返回 [{commodity, severity, message, reason}]
    """
    cfg = config or load_config()
    a_cfg = cfg.get("alerts", {})
    thresh = int(a_cfg.get("score_threshold", 71))
    d1 = int(a_cfg.get("score_change_1d_threshold", 10))
    d7 = int(a_cfg.get("score_change_7d_threshold", 20))

    alerts: list[dict] = []

    for commodity, r in scores.items():
        score = int(r["final_score"])
        c1 = r.get("score_change_1d")
        c7 = r.get("score_change_7d")
        if score >= thresh:
            alerts.append({
                "commodity": commodity, "severity": "critical",
                "reason": f"score_ge_{thresh}",
                "message": f"{commodity} 风险分 {score} ≥ {thresh} ({r['risk_level_label']})",
            })
        if c1 is not None and c1 >= d1:
            alerts.append({
                "commodity": commodity, "severity": "warn",
                "reason": f"score_change_1d_ge_{d1}",
                "message": f"{commodity} 单日上升 +{c1} (-> {score})",
            })
        if c7 is not None and c7 >= d7:
            alerts.append({
                "commodity": commodity, "severity": "warn",
                "reason": f"score_change_7d_ge_{d7}",
                "message": f"{commodity} 7 日累计上升 +{c7} (-> {score})",
            })
        # 等级穿越预警（regime alert）：比单纯阈值更稳定
        regime = r.get("regime_change")
        if regime:
            sev = "warn" if regime.get("direction") == "up" else "info"
            alerts.append({
                "commodity": commodity, "severity": sev,
                "reason": "regime_change",
                "message": (f"{commodity} 等级穿越 "
                            f"{regime['from']} → {regime['to']} "
                            f"({'↑' if regime.get('direction') == 'up' else '↓'} -> {score})"),
            })

    # 关键新闻/政策（events 表中 severity=critical）
    for ev in db.get_recent_events(hours=24):
        if ev.get("severity") == "critical":
            alerts.append({
                "commodity": ev.get("commodity", "all"),
                "severity": "critical",
                "reason": "critical_event",
                "message": f"关键事件：{ev['message']}",
            })

    # 去重
    seen = set()
    uniq = []
    for a in alerts:
        key = (a["commodity"], a["reason"], a["message"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    return uniq


def format_for_channel(alerts: list[dict], score_date: str) -> str:
    if not alerts:
        return f"Commodity Radar [{score_date}] 无新预警"
    lines = [f"📡 *Commodity Radar* `{score_date}` 触发 {len(alerts)} 条预警："]
    for a in alerts:
        lines.append(f"- [{a['severity'].upper()}] {a['commodity']}: {a['message']}")
    return "\n".join(lines)


def dispatch(alerts: list[dict], score_date: str) -> dict[str, str]:
    """把预警发到所有已配置的通道。dry-run 模式下只打印到日志。"""
    logger = get_logger()
    if not alerts:
        logger.info("dispatcher: no alerts to send")
        return {}
    dry_run = os.environ.get("ALERTS_DRY_RUN", "true").lower() == "true"
    text = format_for_channel(alerts, score_date)
    if dry_run:
        logger.info("[ALERTS DRY-RUN]\n%s", text)
        return {ch: "dry-run" for ch, _ in CHANNELS}
    results: dict[str, str] = {}
    for name, send_fn in CHANNELS:
        try:
            res = send_fn(text)
            results[name] = res or "ok"
        except Exception as e:
            logger.warning("alert channel %s failed: %s", name, e)
            results[name] = f"failed: {e}"
    return results
