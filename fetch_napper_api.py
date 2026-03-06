#!/usr/bin/env python3
"""Fetch complete Napper sleep history via API.

Uses auth token extracted from iMazing backup to pull all sleep data
from the Napper API. Token expires 2026-03-23.
"""

import json
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CONFIG = json.load(open(Path(__file__).parent / "config.json"))

API_BASE = "https://api.napper.app"
BABY_ID = CONFIG["baby_id"]
TOKEN_FILE = Path("/tmp/napper_token.txt")
OUTPUT_DIR = Path(__file__).parent / "raw" / "napper_api"

# Fetch in monthly chunks — adjust to your usage dates
START_DATE = date(2022, 11, 1)  # Adjust to your tracking start date
END_DATE = date.today()


def load_token() -> str:
    return TOKEN_FILE.read_text().strip()


def api_get(path: str, token: str) -> dict:
    url = f"{API_BASE}{path}"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    with urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_month(year: int, month: int, token: str) -> list:
    """Fetch all logs for a given month."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    # Don't go past END_DATE
    if end > END_DATE:
        end = END_DATE
    if start > END_DATE:
        return []

    path = f"/logs-between-days/{BABY_ID}/{start.isoformat()}/{end.isoformat()}"
    try:
        data = api_get(path, token)
        items = data.get("items", [])
        return items
    except HTTPError as e:
        print(f"  HTTP {e.code} for {start} - {end}")
        return []


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    token = load_token()

    # Test auth
    print("Testing auth...")
    try:
        babies = api_get("/babies", token)
        print(f"  Authenticated. Baby: {babies['items'][0]['name']}")
    except HTTPError as e:
        print(f"  Auth failed: HTTP {e.code}. Token may be expired.")
        return

    # Fetch all months
    all_events = []
    current = START_DATE
    while current <= END_DATE:
        year, month = current.year, current.month
        print(f"Fetching {year}-{month:02d}...", end=" ", flush=True)
        events = fetch_month(year, month, token)
        print(f"{len(events)} events")
        all_events.extend(events)

        # Save per-month file
        month_file = OUTPUT_DIR / f"{year}-{month:02d}.json"
        with open(month_file, "w") as f:
            json.dump(events, f, indent=2)

        # Next month
        if month == 12:
            current = date(year + 1, 1, 1)
        else:
            current = date(year, month + 1, 1)

        time.sleep(1)  # Be polite

    # Save combined file
    combined_path = OUTPUT_DIR / "all_events.json"
    with open(combined_path, "w") as f:
        json.dump(all_events, f, indent=2)

    # Organize by date
    by_date = {}
    for ev in all_events:
        # Extract date from start timestamp
        start = ev.get("start", "")
        if start:
            d = start[:10]
            by_date.setdefault(d, []).append(ev)

    logs_path = OUTPUT_DIR / "sleep_logs_full.json"
    with open(logs_path, "w") as f:
        json.dump(dict(sorted(by_date.items())), f, indent=2)

    print(f"\nDone!")
    print(f"  Total events: {len(all_events)}")
    print(f"  Total days with data: {len(by_date)}")
    if by_date:
        dates = sorted(by_date.keys())
        print(f"  Date range: {dates[0]} to {dates[-1]}")
    print(f"  Combined file: {combined_path}")
    print(f"  By-date file: {logs_path}")


if __name__ == "__main__":
    main()
