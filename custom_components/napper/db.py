"""Local SQLite database operations for Napper."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create napper_events table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS napper_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            event_type TEXT,
            start_iso TEXT,
            end_iso TEXT,
            start_time TEXT,
            end_time TEXT,
            duration_min REAL,
            skipped BOOLEAN,
            comment TEXT,
            how_baby_slept TEXT,
            created_by TEXT,
            start_time_tz TEXT,
            end_time_tz TEXT
        )
    """)
    conn.commit()


def _time_from_iso(iso: str) -> str:
    """Extract HH:MM from ISO timestamp."""
    return iso[11:16] if len(iso) >= 16 else ""


def log_event(db_path: str, category: str, start_iso: str, end_iso: str | None = None) -> None:
    """Insert a new event into the local database."""
    path = Path(db_path)
    conn = sqlite3.connect(path)
    _ensure_table(conn)

    date_str = start_iso[:10] if start_iso else ""
    start_time = _time_from_iso(start_iso) if start_iso else ""
    end_time = _time_from_iso(end_iso) if end_iso else ""

    duration = None
    if start_iso and end_iso:
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            s = datetime.strptime(start_iso[:19], fmt)
            e = datetime.strptime(end_iso[:19], fmt)
            diff = (e - s).total_seconds() / 60
            duration = round(diff, 1) if diff > 0 else None
        except (ValueError, TypeError):
            pass

    conn.execute(
        """INSERT INTO napper_events
           (date, event_type, start_iso, end_iso, start_time, end_time,
            duration_min, skipped, comment, how_baby_slept, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (date_str, category, start_iso, end_iso, start_time, end_time,
         duration, False, "", "", "home_assistant"),
    )
    conn.commit()
    conn.close()
    _LOGGER.info("Logged %s event to %s", category, path)


def end_nap(db_path: str, end_iso: str) -> None:
    """Set the end time on the most recent NAP event that has no end."""
    path = Path(db_path)
    conn = sqlite3.connect(path)
    _ensure_table(conn)

    row = conn.execute(
        """SELECT id, start_iso FROM napper_events
           WHERE event_type = 'NAP' AND (end_iso IS NULL OR end_iso = '')
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()

    if row:
        event_id, start_iso = row
        duration = None
        if start_iso:
            try:
                fmt = "%Y-%m-%dT%H:%M:%S"
                s = datetime.strptime(start_iso[:19], fmt)
                e = datetime.strptime(end_iso[:19], fmt)
                diff = (e - s).total_seconds() / 60
                duration = round(diff, 1) if diff > 0 else None
            except (ValueError, TypeError):
                pass

        end_time = _time_from_iso(end_iso)
        conn.execute(
            """UPDATE napper_events
               SET end_iso = ?, end_time = ?, duration_min = ?
               WHERE id = ?""",
            (end_iso, end_time, duration, event_id),
        )
        conn.commit()
        _LOGGER.info("Ended nap (id=%s) at %s, duration=%.1f min", event_id, end_time, duration or 0)
    else:
        _LOGGER.warning("No open nap found to end")

    conn.close()
