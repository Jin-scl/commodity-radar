"""SQLite 存储层 — 指标快照、评分历史、事件、抓取日志。

设计原则：
- 所有写入幂等（UPSERT），同一品种+指标+时间戳只保留一条
- 评分按 commodity+score_date 唯一
- 查询函数返回 dict / list[dict]，便于直接喂给 Jinja2 模板
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity   TEXT NOT NULL,
    name        TEXT NOT NULL,
    value_num   REAL,
    value_text  TEXT,
    unit        TEXT,
    source      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    confidence  TEXT NOT NULL DEFAULT 'medium',
    is_manual   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT,
    UNIQUE(commodity, name, timestamp) ON CONFLICT REPLACE
);
CREATE INDEX IF NOT EXISTS idx_ind_commodity_name ON indicators(commodity, name);
CREATE INDEX IF NOT EXISTS idx_ind_fetched_at ON indicators(fetched_at);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity         TEXT NOT NULL,
    score_date        TEXT NOT NULL,
    raw_score         INTEGER NOT NULL,
    final_score       INTEGER NOT NULL,
    risk_level        TEXT NOT NULL,
    risk_level_label  TEXT NOT NULL,
    score_change_1d   INTEGER,
    score_change_7d   INTEGER,
    confidence_score  INTEGER,                              -- 0-100，数据置信度均值
    bullish_json      TEXT NOT NULL DEFAULT '[]',
    bearish_json      TEXT NOT NULL DEFAULT '[]',
    triggered_alerts_json TEXT NOT NULL DEFAULT '[]',
    triggered_rules_json  TEXT NOT NULL DEFAULT '[]',       -- 触发规则 id 列表（用于变化来源 diff）
    payload_json      TEXT,
    computed_at       TEXT NOT NULL,
    UNIQUE(commodity, score_date) ON CONFLICT REPLACE
);
CREATE INDEX IF NOT EXISTS idx_scores_date ON scores(score_date);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    commodity   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    message     TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'info',
    source      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_commodity ON events(commodity);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetcher       TEXT NOT NULL,
    run_at        TEXT NOT NULL,
    status        TEXT NOT NULL,
    records_count INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    duration_ms   INTEGER
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)
            # 幂等迁移：旧 DB 缺新列时补上
            self._migrate(c)

    def _migrate(self, c) -> None:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(scores)").fetchall()}
        if "confidence_score" not in cols:
            c.execute("ALTER TABLE scores ADD COLUMN confidence_score INTEGER")
        if "triggered_rules_json" not in cols:
            c.execute("ALTER TABLE scores ADD COLUMN "
                      "triggered_rules_json TEXT NOT NULL DEFAULT '[]'")

    # ---------- indicators ----------
    def save_indicator(self, ind: dict) -> None:
        """ind 字段：commodity, name, value_num, value_text, unit, source,
        timestamp, fetched_at, confidence, is_manual, notes."""
        fields = ["commodity", "name", "value_num", "value_text", "unit",
                  "source", "timestamp", "fetched_at", "confidence",
                  "is_manual", "notes"]
        row = {f: ind.get(f) for f in fields}
        if not row["fetched_at"]:
            row["fetched_at"] = now_iso()
        if not row["timestamp"]:
            row["timestamp"] = row["fetched_at"]
        row["is_manual"] = 1 if row.get("is_manual") else 0
        row["confidence"] = row.get("confidence") or "medium"
        placeholders = ", ".join("?" for _ in fields)
        cols = ", ".join(fields)
        with self._conn() as c:
            c.execute(f"INSERT INTO indicators ({cols}) VALUES ({placeholders})",
                      [row[f] for f in fields])

    def save_indicators(self, inds: Iterable[dict]) -> int:
        n = 0
        for ind in inds:
            self.save_indicator(ind)
            n += 1
        return n

    def get_latest_indicators(self, commodity: str | None = None,
                              names: Iterable[str] | None = None,
                              as_of_date: str | None = None,
                              include_seed: bool = False) -> list[dict]:
        """每个 (commodity, name) 取 timestamp 最大那条。

        as_of_date: "YYYY-MM-DD" — 只看 timestamp <= 该日期；用于 --date 回放
        include_seed: 是否包含 source='seed' 的记录（默认排除，避免污染最新快照）

        同 timestamp 下用 id DESC 兜底（保证去重稳定）。
        """
        # 子查询：每个 (commodity, name) 在过滤条件下的最新 (timestamp, id)
        sub_filters = []
        sub_params: list[Any] = []
        if not include_seed:
            sub_filters.append("source != 'seed'")
        if as_of_date:
            # 取 timestamp 的日期前缀比较，覆盖 "YYYY-MM-DD" 和 "YYYY-MM-DDT..." 两种
            sub_filters.append("substr(timestamp, 1, 10) <= ?")
            sub_params.append(as_of_date)
        where = ("WHERE " + " AND ".join(sub_filters)) if sub_filters else ""

        sql = f"""
        SELECT i.* FROM indicators i
        JOIN (
            SELECT commodity, name, MAX(timestamp) AS mts
            FROM indicators
            {where}
            GROUP BY commodity, name
        ) latest
        ON i.commodity = latest.commodity
        AND i.name = latest.name
        AND i.timestamp = latest.mts
        WHERE 1=1
        """
        params: list[Any] = list(sub_params)
        if not include_seed:
            sql += " AND i.source != 'seed'"
        if commodity:
            sql += " AND i.commodity = ?"
            params.append(commodity)
        if names:
            names_list = list(names)
            placeholders = ",".join("?" for _ in names_list)
            sql += f" AND i.name IN ({placeholders})"
            params.extend(names_list)
        # 同 (commodity, name, timestamp) 下保留 id 最大的（最近写入）
        sql += " ORDER BY i.id DESC"

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        # 主查询会 JOIN 出多行（同一 timestamp 多次写入时），用 dict 去重
        seen = set()
        out = []
        for r in rows:
            key = (r["commodity"], r["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(r))
        return out

    def get_indicator_history(self, commodity: str, name: str,
                              days: int = 30) -> list[dict]:
        # 用日期字符串比较；indicator timestamp 可能是 "2026-05-30"
        # 或 "2026-05-30T22:00:00+08:00"，两种格式都按字典序 >= 'YYYY-MM-DD'
        # 即覆盖该日及之后所有时刻。
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._conn() as c:
            rows = c.execute(
                """SELECT * FROM indicators
                   WHERE commodity = ? AND name = ? AND timestamp >= ?
                   ORDER BY timestamp ASC""",
                (commodity, name, since),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- scores ----------
    def save_score(self, score: dict) -> None:
        fields = ["commodity", "score_date", "raw_score", "final_score",
                  "risk_level", "risk_level_label", "score_change_1d",
                  "score_change_7d", "confidence_score",
                  "bullish_json", "bearish_json",
                  "triggered_alerts_json", "triggered_rules_json",
                  "payload_json", "computed_at"]
        row = {f: score.get(f) for f in fields}
        if not row["computed_at"]:
            row["computed_at"] = now_iso()
        for k in ("bullish_json", "bearish_json",
                  "triggered_alerts_json", "triggered_rules_json"):
            if isinstance(row.get(k), (list, dict)):
                row[k] = json.dumps(row[k], ensure_ascii=False)
            elif row.get(k) is None:
                row[k] = "[]"
        if isinstance(row.get("payload_json"), (list, dict)):
            row["payload_json"] = json.dumps(row["payload_json"], ensure_ascii=False)
        placeholders = ", ".join("?" for _ in fields)
        cols = ", ".join(fields)
        with self._conn() as c:
            c.execute(f"INSERT INTO scores ({cols}) VALUES ({placeholders})",
                      [row[f] for f in fields])

    def get_score(self, commodity: str, score_date: str) -> dict | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM scores WHERE commodity = ? AND score_date = ?",
                (commodity, score_date),
            ).fetchone()
        return dict(r) if r else None

    def get_score_n_days_ago(self, commodity: str, days_back: int,
                             reference_date: str | None = None) -> dict | None:
        ref = datetime.strptime(reference_date or today_str(), "%Y-%m-%d")
        target = (ref - timedelta(days=days_back)).strftime("%Y-%m-%d")
        with self._conn() as c:
            # 找 target 当天或最接近的一条（向前回溯）
            r = c.execute(
                """SELECT * FROM scores
                   WHERE commodity = ? AND score_date <= ?
                   ORDER BY score_date DESC LIMIT 1""",
                (commodity, target),
            ).fetchone()
        return dict(r) if r else None

    def get_latest_scores(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT s.* FROM scores s
                   JOIN (
                       SELECT commodity, MAX(score_date) AS m
                       FROM scores GROUP BY commodity
                   ) x
                   ON s.commodity = x.commodity AND s.score_date = x.m
                   ORDER BY s.commodity"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- events ----------
    def save_event(self, commodity: str, event_type: str, message: str,
                   severity: str = "info", source: str | None = None,
                   timestamp: str | None = None) -> None:
        """timestamp 优先用调用方传入的（事件真实发生时间），
        缺省时用 now_iso()（系统记录时间）。"""
        ts = timestamp or now_iso()
        with self._conn() as c:
            c.execute(
                """INSERT INTO events (timestamp, commodity, event_type, message,
                                       severity, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, commodity, event_type, message, severity, source),
            )

    def get_recent_events(self, hours: int = 24,
                          commodity: str | None = None) -> list[dict]:
        """最近 N 小时内的 events。

        兼容两种 timestamp 格式：
        - date-only "YYYY-MM-DD"（manual event，按当天 00:00 算）
        - ISO datetime "YYYY-MM-DDTHH:MM:SS±HH:MM"（系统写入）
        用 substr(timestamp, 1, 10) 做日期级前置过滤，再交由 Python 做精细判断。
        """
        since = datetime.now(timezone.utc).astimezone() - timedelta(hours=hours)
        since_date = since.strftime("%Y-%m-%d")
        since_iso = since.isoformat()
        sql = "SELECT * FROM events WHERE substr(timestamp, 1, 10) >= ?"
        params: list[Any] = [since_date]
        if commodity:
            sql += " AND commodity = ?"
            params.append(commodity)
        sql += " ORDER BY timestamp DESC"
        with self._conn() as c:
            candidates = [dict(r) for r in c.execute(sql, params).fetchall()]
        # 二次精筛：date-only 的当作 00:00:00 算
        out = []
        for ev in candidates:
            ts = ev.get("timestamp", "")
            if len(ts) == 10:
                # date-only：如果日期 >= since_date 就纳入（按 00:00 算）
                if ts >= since_date:
                    out.append(ev)
            else:
                if ts >= since_iso:
                    out.append(ev)
        return out

    def get_events_between(self, start: str, end: str,
                           commodity: str | None = None) -> list[dict]:
        """[start, end) 区间内的 events；用于 --date 按日期回放预警。

        start/end 支持 'YYYY-MM-DD' 或 ISO datetime 字符串。
        使用 substr(timestamp, 1, 10) 做日期级比较，覆盖两种格式。
        """
        sql = ("SELECT * FROM events WHERE "
               "substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) < ?")
        params: list[Any] = [start[:10], end[:10]]
        if commodity:
            sql += " AND commodity = ?"
            params.append(commodity)
        sql += " ORDER BY timestamp DESC"
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    # ---------- fetch_log ----------
    def log_fetch(self, fetcher: str, status: str, records_count: int = 0,
                  error: str | None = None, duration_ms: int | None = None) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO fetch_log (fetcher, run_at, status, records_count,
                                          error, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (fetcher, now_iso(), status, records_count, error, duration_ms),
            )

    def get_recent_fetch_failures(self, hours: int = 24) -> list[dict]:
        since = (datetime.now(timezone.utc).astimezone()
                 - timedelta(hours=hours)).isoformat()
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                """SELECT * FROM fetch_log
                   WHERE status != 'success' AND run_at >= ?
                   ORDER BY run_at DESC""",
                (since,),
            ).fetchall()]
