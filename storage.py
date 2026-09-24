"""
Хранит снепшоты статистики каналов на диске (SQLite), чтобы со временем можно было
честно посчитать рост: сколько подписчиков канал набрал с момента, когда бот
начал его отслеживать.

Важно понимать: YouTube API не отдаёт историю подписчиков за прошлые периоды.
Поэтому "рост за год" — это не ретроспектива, а рост с даты первого снепшота,
которая будет расти по мере того, как бот работает. День запуска — это и есть
день "0" для каждого канала. Чем дольше бот работает, тем точнее эта метрика.
"""

import datetime
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channel_history.db")


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_snapshots (
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                subscriber_count INTEGER,
                snapshot_date TEXT NOT NULL,
                PRIMARY KEY (channel_id, snapshot_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notify_settings (
                chat_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                interval_hours REAL NOT NULL DEFAULT 2,
                last_sent_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pulse_state (
                chat_id TEXT PRIMARY KEY,
                top_video_ids TEXT
            )
        """)


def record_snapshot(channel_id: str, channel_title: str, subscriber_count):
    """Пишет снепшот раз в день на канал (повторный вызов в тот же день просто обновит title)."""
    if subscriber_count is None:
        return
    today = datetime.date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO channel_snapshots (channel_id, channel_title, subscriber_count, snapshot_date)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(channel_id, snapshot_date)
               DO UPDATE SET subscriber_count=excluded.subscriber_count, channel_title=excluded.channel_title""",
            (channel_id, channel_title, subscriber_count, today),
        )


def get_breakout_channels(min_days_tracked: int = 1, limit: int = 30) -> list:
    """
    Возвращает каналы, отсортированные по приросту подписчиков с первого снепшота.
    Каждый элемент: dict(channel_id, channel_title, first_date, first_subs,
                          last_date, last_subs, growth_abs, growth_pct, days_tracked)
    """
    with _conn() as conn:
        rows = conn.execute("""
            SELECT channel_id, channel_title, snapshot_date, subscriber_count
            FROM channel_snapshots
            ORDER BY channel_id, snapshot_date ASC
        """).fetchall()

    by_channel = {}
    for channel_id, title, date, subs in rows:
        by_channel.setdefault(channel_id, []).append((date, title, subs))

    results = []
    today = datetime.date.today()
    for channel_id, entries in by_channel.items():
        first_date, first_title, first_subs = entries[0]
        last_date, last_title, last_subs = entries[-1]
        if first_subs is None or last_subs is None:
            continue
        days_tracked = (
            datetime.date.fromisoformat(last_date) - datetime.date.fromisoformat(first_date)
        ).days
        if days_tracked < min_days_tracked:
            continue
        growth_abs = last_subs - first_subs
        growth_pct = (growth_abs / first_subs * 100) if first_subs > 0 else 0
        results.append({
            "channel_id": channel_id,
            "channel_title": last_title,
            "first_date": first_date,
            "first_subs": first_subs,
            "last_date": last_date,
            "last_subs": last_subs,
            "growth_abs": growth_abs,
            "growth_pct": growth_pct,
            "days_tracked": days_tracked,
        })

    results.sort(key=lambda r: r["growth_abs"], reverse=True)
    return results[:limit]


def tracking_started_date() -> str:
    with _conn() as conn:
        row = conn.execute("SELECT MIN(snapshot_date) FROM channel_snapshots").fetchone()
    return row[0] if row and row[0] else "ещё нет данных"


def set_notify(chat_id: str, enabled: bool, interval_hours: float = None):
    with _conn() as conn:
        existing = conn.execute(
            "SELECT interval_hours FROM notify_settings WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if interval_hours is None:
            interval_hours = existing[0] if existing else 2.0
        conn.execute(
            """INSERT INTO notify_settings (chat_id, enabled, interval_hours, last_sent_at)
               VALUES (?, ?, ?, NULL)
               ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled, interval_hours=?""",
            (chat_id, int(enabled), interval_hours, interval_hours),
        )


def get_notify_settings(chat_id: str):
    with _conn() as conn:
        row = conn.execute(
            "SELECT enabled, interval_hours, last_sent_at FROM notify_settings WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
    if not row:
        return {"enabled": False, "interval_hours": 2.0, "last_sent_at": None}
    return {"enabled": bool(row[0]), "interval_hours": row[1], "last_sent_at": row[2]}


def get_all_enabled_notify_chats() -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT chat_id, interval_hours, last_sent_at FROM notify_settings WHERE enabled=1"
        ).fetchall()
    return [{"chat_id": r[0], "interval_hours": r[1], "last_sent_at": r[2]} for r in rows]


def mark_notify_sent(chat_id: str, sent_at_iso: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE notify_settings SET last_sent_at=? WHERE chat_id=?", (sent_at_iso, chat_id)
        )


def get_pulse_state(chat_id: str) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT top_video_ids FROM pulse_state WHERE chat_id=?", (chat_id,)
        ).fetchone()
    if not row or not row[0]:
        return {}
    # формат: "video_id:views,video_id:views,..."
    result = {}
    for pair in row[0].split(","):
        if ":" in pair:
            vid, views = pair.split(":", 1)
            result[vid] = int(views)
    return result


def set_pulse_state(chat_id: str, video_views: dict):
    serialized = ",".join(f"{vid}:{views}" for vid, views in video_views.items())
    with _conn() as conn:
        conn.execute(
            """INSERT INTO pulse_state (chat_id, top_video_ids) VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET top_video_ids=excluded.top_video_ids""",
            (chat_id, serialized),
        )


init_db()
