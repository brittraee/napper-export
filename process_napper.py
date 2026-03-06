#!/usr/bin/env python3
"""Process extracted Napper data into CSV and SQLite formats."""

import csv
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python < 3.9

CONFIG_PATH = Path(__file__).parent / "config.json"
RAW_DIR = Path(__file__).parent / "raw" / "napper"
API_DIR = Path(__file__).parent / "raw" / "napper_api"
PROCESSED_DIR = Path(__file__).parent / "processed"
DB_PATH = Path(__file__).parent / "sleep.db"

# Load optional timezone from config
TARGET_TZ = None
if CONFIG_PATH.exists():
    cfg = json.load(open(CONFIG_PATH))
    tz_name = cfg.get("timezone")
    if tz_name:
        TARGET_TZ = ZoneInfo(tz_name)
        print(f"Normalizing times to: {tz_name}")


def parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO timestamp into a timezone-aware datetime."""
    if not ts:
        return None
    try:
        # Handle offset formats: -06:00, -0600, Z
        clean = ts.strip()
        # Python 3.10 doesn't handle colon in offset for all format strings,
        # so normalize to +/-HHMM
        m = re.search(r'([+-])(\d{2}):(\d{2})$', clean)
        if m:
            clean = clean[:m.start()] + m.group(1) + m.group(2) + m.group(3)
        clean = clean.replace("Z", "+0000")

        for fmt in ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                     "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(clean, fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def to_target_tz(dt: datetime | None) -> datetime | None:
    """Convert a datetime to the configured target timezone."""
    if dt is None or TARGET_TZ is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(TARGET_TZ)
    # Assume UTC if no timezone info
    return dt.replace(tzinfo=timezone.utc).astimezone(TARGET_TZ)


def parse_time(ts: str | None) -> str | None:
    """Extract HH:MM from an ISO timestamp (original local time)."""
    if not ts:
        return None
    try:
        parts = ts.split("T")
        if len(parts) >= 2:
            time_part = parts[1].split(".")[0]
            return time_part[:5]
    except (IndexError, ValueError):
        pass
    return None


def parse_time_tz(ts: str | None) -> str | None:
    """Extract HH:MM normalized to target timezone."""
    dt = parse_iso(ts)
    converted = to_target_tz(dt)
    if converted:
        return f"{converted.hour:02d}:{converted.minute:02d}"
    return None


def calc_duration_min(start: str | None, end: str | None) -> float | None:
    """Calculate duration in minutes between two ISO timestamps."""
    s = parse_iso(start)
    e = parse_iso(end)
    if s and e:
        diff = (e - s).total_seconds() / 60
        return round(diff, 1) if diff > 0 else None
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
        wake_ts = None
        nap_start_ts = None
        nap_end_ts = None
        nap_duration = None
        nap_skipped = False
        bed_ts = None
        how_slept = ""

        for log in day_logs:
            cat = log.get("category")
            if cat == "WOKE_UP":
                wake_ts = log.get("start")
            elif cat == "NAP":
                if log.get("skipped") or log.get("isSkipped"):
                    nap_skipped = True
                else:
                    nap_start_ts = log.get("start")
                    nap_end_ts = log.get("end")
                    nap_duration = calc_duration_min(nap_start_ts, nap_end_ts)
                    how_slept = log.get("howBabySlept", "")
            elif cat == "BED_TIME":
                bed_ts = log.get("start")

        row = {
            "date": date,
            "wake_time": parse_time(wake_ts),
            "nap_start": parse_time(nap_start_ts),
            "nap_end": parse_time(nap_end_ts),
            "nap_duration_min": nap_duration,
            "nap_skipped": nap_skipped,
            "bedtime": parse_time(bed_ts),
            "how_baby_slept": how_slept,
        }
        if TARGET_TZ:
            row["wake_time_tz"] = parse_time_tz(wake_ts)
            row["nap_start_tz"] = parse_time_tz(nap_start_ts)
            row["nap_end_tz"] = parse_time_tz(nap_end_ts)
            row["bedtime_tz"] = parse_time_tz(bed_ts)
        daily_rows.append(row)

    daily_path = PROCESSED_DIR / "napper_daily.csv"
    with open(daily_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=daily_rows[0].keys())
        writer.writeheader()
        writer.writerows(daily_rows)
    print(f"Daily summary: {len(daily_rows)} rows -> {daily_path}")

    # --- Build events CSV ---
    events_rows = []
    for ev in events_raw:
        start_ts = ev.get("start")
        end_ts = ev.get("end")
        duration = calc_duration_min(start_ts, end_ts)
        row = {
            "date": ev.get("date", ""),
            "event_type": ev.get("category", ""),
            "start": start_ts,
            "end": end_ts,
            "start_time": parse_time(start_ts),
            "end_time": parse_time(end_ts),
            "duration_min": duration,
            "skipped": ev.get("skipped", ev.get("isSkipped", False)),
            "comment": ev.get("comment", ""),
            "how_baby_slept": ev.get("howBabySlept", ev.get("how_baby_slept", "")),
            "created_by": ev.get("createdByUserId", ev.get("created_by", "")),
        }
        if TARGET_TZ:
            row["start_time_tz"] = parse_time_tz(start_ts)
            row["end_time_tz"] = parse_time_tz(end_ts)
        events_rows.append(row)

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

    tz_cols = ""
    if TARGET_TZ:
        tz_cols = """
            ,wake_time_tz TEXT
            ,nap_start_tz TEXT
            ,nap_end_tz TEXT
            ,bedtime_tz TEXT"""

    c.execute(f"""
        CREATE TABLE napper_daily (
            date TEXT PRIMARY KEY,
            wake_time TEXT,
            nap_start TEXT,
            nap_end TEXT,
            nap_duration_min REAL,
            nap_skipped BOOLEAN,
            bedtime TEXT,
            how_baby_slept TEXT
            {tz_cols}
        )
    """)

    ev_tz_cols = ""
    if TARGET_TZ:
        ev_tz_cols = """
            ,start_time_tz TEXT
            ,end_time_tz TEXT"""

    c.execute(f"""
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
            {ev_tz_cols}
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
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        c.execute(
            f"INSERT INTO napper_daily ({', '.join(cols)}) VALUES ({placeholders})",
            [row[k] for k in cols]
        )

    # Insert events
    # Map CSV column names to DB column names
    ev_col_map = {"start": "start_iso", "end": "end_iso"}
    for row in events_rows:
        cols = [ev_col_map.get(k, k) for k in row.keys()]
        placeholders = ", ".join(["?"] * len(cols))
        c.execute(
            f"INSERT INTO napper_events ({', '.join(cols)}) VALUES ({placeholders})",
            list(row.values())
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
