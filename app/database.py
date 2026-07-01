import sqlite3
from pathlib import Path

DB_PATH = Path("data/countdown.db")


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                channel_id INTEGER,
                event_name TEXT,
                event_time_utc TEXT
            )
        """)


def save_guild_settings(guild_id: int, role_id: int, category_id: int):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO guild_settings (guild_id, role_id, category_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                role_id = excluded.role_id,
                category_id = excluded.category_id
        """, (guild_id, role_id, category_id))


def get_guild_settings(guild_id: int):
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()


def get_all_active_events():
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("""
            SELECT *
            FROM guild_settings
            WHERE channel_id IS NOT NULL
              AND event_name IS NOT NULL
              AND event_time_utc IS NOT NULL
        """).fetchall()


def save_event(guild_id: int, channel_id: int, event_name: str, event_time_utc: str):
    with get_connection() as conn:
        conn.execute("""
            UPDATE guild_settings
            SET channel_id = ?, event_name = ?, event_time_utc = ?
            WHERE guild_id = ?
        """, (channel_id, event_name, event_time_utc, guild_id))