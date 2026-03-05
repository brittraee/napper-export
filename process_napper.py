#!/usr/bin/env python3
"""Process extracted Napper data into CSV and SQLite formats."""

import csv
import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw" / "napper"
API_DIR = Path(__file__).parent / "raw" / "napper_api"
PROCESSED_DIR = Path(__file__).parent / "processed"
DB_PATH = Path(__file__).parent / "silas_sleep.db"


def parse_time(ts: str | None) -> str | None:
    """Extract HH:MM from an ISO timestamp like 2025-12-25T07:50:00.000-06:00."""
    if not ts:
        return None
    try:
        # Parse the local time portion directly (already in local tz)
        parts = ts.split("T")
        if len(parts) >= 2:
            time_part = parts[1].split(".")[0]  # HH:MM:SS
            return time_part[:5]  # HH:MM
    except (IndexError, ValueError):
        pass
    return None


def parse_datetime(ts: str | None) -> str | None:
    """Return full ISO datetime string."""
    if not ts:
        return None
    # Normalize: keep as-is (already has timezone)
    return ts


def calc_duration_min(start: str | None, end: str | None) -> float | None:
    """Calculate duration in minutes between two ISO timestamps."""
    if not start or not end:
        return None
    try:
        # Parse ISO format with timezone
        fmt_patterns = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]
        s = e = None
        for fmt in fmt_patterns:
            # Handle -06:00 offset format
            start_clean = start.replace("-06:00", "-0600").replace("-05:00", "-0500")
            end_clean = end.replace("-06:00", "-0600").replace("-05:00", "-0500")
            try:
                s = datetime.strptime(start_clean, fmt)
                e = datetime.strptime(end_clean, fmt)
                break
            except ValueError:
                continue
        if s and e:
            diff = (e - s).total_seconds() / 60
            return round(diff, 1) if diff > 0 else None
    except Exception:
        pass
    return None


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # Load raw data — prefer API data (complete history), fall back to MMKV cache
    api_logs_file = API_DIR / "sleep_logs_full.json"
    if api_logs_file.exists():
        print("Using API data (complete history)")
        logs = json.load(open(api_logs_file))
        # API events use 'category' not 'category', and field names match
        events_raw = json.load(open(API_DIR / "all_events.json"))
        # Normalize API events to match expected format
        for ev in events_raw:
            if "date" not in ev:
                start = ev.get("start", "")
                ev["date"] = start[:10] if start else ""
    else:
        print("Using MMKV cache data (limited history)")
        logs = json.load(open(RAW_DIR / "sleep_logs.json"))
        events_raw = json.load(open(RAW_DIR / "sleep_events.json"))

    stats_file = RAW_DIR / "sleep_stats.json"
    stats = json.load(open(stats_file)) if stats_file.exists() else {}

    # --- Build daily summary CSV ---
    daily_rows = []
    for date, day_logs in sorted(logs.items()):
        wake_time = None
        nap_start = None
        nap_end = None
        nap_duration = None
        nap_skipped = False
        bedtime = None
        how_slept = ""

        for log in day_logs:
            cat = log.get("category")
            if cat == "WOKE_UP":
                wake_time = parse_time(log.get("start"))
            elif cat == "NAP":
                if log.get("skipped") or log.get("isSkipped"):
                    nap_skipped = True
                else:
                    nap_start = parse_time(log.get("start"))
                    nap_end = parse_time(log.get("end"))
                    nap_duration = calc_duration_min(log.get("start"), log.get("end"))
                    how_slept = log.get("howBabySlept", "")
            elif cat == "BED_TIME":
                bedtime = parse_time(log.get("start"))

        daily_rows.append({
            "date": date,
            "wake_time": wake_time,
            "nap_start": nap_start,
            "nap_end": nap_end,
            "nap_duration_min": nap_duration,
            "nap_skipped": nap_skipped,
            "bedtime": bedtime,
            "how_baby_slept": how_slept,
        })

    daily_path = PROCESSED_DIR / "napper_daily.csv"
    with open(daily_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=daily_rows[0].keys())
        writer.writeheader()
        writer.writerows(daily_rows)
    print(f"Daily summary: {len(daily_rows)} rows -> {daily_path}")

    # --- Build events CSV ---
    events_rows = []
    for ev in events_raw:
        duration = calc_duration_min(ev.get("start"), ev.get("end"))
        events_rows.append({
            "date": ev.get("date", ""),
            "event_type": ev.get("category", ""),
            "start": ev.get("start"),
            "end": ev.get("end"),
            "start_time": parse_time(ev.get("start")),
            "end_time": parse_time(ev.get("end")),
            "duration_min": duration,
            "skipped": ev.get("skipped", ev.get("isSkipped", False)),
            "comment": ev.get("comment", ""),
            "how_baby_slept": ev.get("howBabySlept", ev.get("how_baby_slept", "")),
            "created_by": ev.get("createdByUserId", ev.get("created_by", "")),
        })

    events_path = PROCESSED_DIR / "napper_events.csv"
    with open(events_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=events_rows[0].keys())
        writer.writeheader()
        writer.writerows(events_rows)
    print(f"Events: {len(events_rows)} rows -> {events_path}")

    # --- Build SQLite database ---
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE napper_daily (
            date TEXT PRIMARY KEY,
            wake_time TEXT,
            nap_start TEXT,
            nap_end TEXT,
            nap_duration_min REAL,
            nap_skipped BOOLEAN,
            bedtime TEXT,
            how_baby_slept TEXT
        )
    """)

    c.execute("""
        CREATE TABLE napper_events (
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
            created_by TEXT
        )
    """)

    c.execute("""
        CREATE TABLE napper_stats (
            date TEXT,
            day TEXT,
            wake_up BOOLEAN,
            num_of_naps INTEGER,
            bed_time BOOLEAN,
            expected_num_of_naps INTEGER,
            is_completed BOOLEAN
        )
    """)

    # Insert daily data
    for row in daily_rows:
        c.execute(
            "INSERT INTO napper_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["date"], row["wake_time"], row["nap_start"], row["nap_end"],
             row["nap_duration_min"], row["nap_skipped"], row["bedtime"],
             row["how_baby_slept"])
        )

    # Insert events
    for row in events_rows:
        c.execute(
            "INSERT INTO napper_events (date, event_type, start_iso, end_iso, start_time, end_time, duration_min, skipped, comment, how_baby_slept, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["date"], row["event_type"], row["start"], row["end"],
             row["start_time"], row["end_time"], row["duration_min"],
             row["skipped"], row["comment"], row["how_baby_slept"],
             row["created_by"])
        )

    # Insert stats
    for stats_date, day_stats in stats.items():
        for entry in day_stats:
            if isinstance(entry, dict) and "day" in entry:
                c.execute(
                    "INSERT INTO napper_stats VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (stats_date, entry.get("day"), entry.get("wakeUp"),
                     entry.get("numOfNaps"), entry.get("bedTime"),
                     entry.get("expectedNumOfNaps"), entry.get("isCompleted"))
                )

    conn.commit()

    # Summary
    for table in ["napper_daily", "napper_events", "napper_stats"]:
        count = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")

    date_range = c.execute("SELECT MIN(date), MAX(date) FROM napper_daily").fetchone()
    print(f"\nSQLite DB -> {DB_PATH}")
    print(f"  Date range: {date_range[0]} to {date_range[1]}")

    conn.close()


if __name__ == "__main__":
    main()
