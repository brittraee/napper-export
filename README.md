# napper-export

Export your child's complete sleep data from the [Napper](https://getnapper.com) app.

Napper doesn't offer a data export feature. This project extracts your sleep data through two methods:

1. **Local backup extraction** — Parse Napper's MMKV cache from an iOS backup (limited to recently cached days)
2. **API fetch** — Use your own auth token to pull complete history from Napper's API

## Why

I wanted a portable copy of my son's sleep data — 3 years of wake times, naps, bedtimes, night wakings. The app stores everything server-side with no export option. GDPR data requests went unanswered (bounced by Apple's Hide My Email relay). So I built this.

The local backup approach only recovered ~45 days out of 1,000+ because Napper's MMKV cache rolls over every 7-10 days. The API approach recovered everything.

## What You Get

```
processed/
  napper_daily.csv     One row per day (wake time, nap, bedtime)
  napper_events.csv    One row per event (all categories)
silas_sleep.db         SQLite database
raw/
  napper_api/          Complete JSON from API (organized by month)
  napper/              MMKV extraction (partial, for reference)
  nara/                Nara Baby data (if you used that app)
```

## Quick Start

### Prerequisites

- macOS with Python 3.10+
- [iMazing](https://imazing.com) with at least one completed backup
- An active Napper account

### Setup

```bash
git clone https://github.com/YOUR_USER/napper-export.git
cd napper-export

# Auto-detect your device, find file hashes, and create config.json
python3 find_hashes.py
```

### Method 1: API Fetch (Recommended — Gets Complete History)

```bash
# Extract your auth token from the backup
python3 extract_token.py

# Fetch all sleep data from the API
python3 fetch_napper_api.py

# Process into CSV + SQLite
python3 process_napper.py
```

The auth token is valid for ~30 days from your last app login. If it's expired, open Napper on your phone, wait a moment, run a new iMazing backup, and re-extract.

### Method 2: Local Backup Only (Partial)

If you'd rather not make API calls:

```bash
python3 extract_napper.py    # Parse MMKV from backup
python3 process_napper.py    # Generate CSV + SQLite
```

This only captures days that were in Napper's local cache at backup time (~7-10 days per backup snapshot).

## How It Works

### MMKV Extraction

Napper uses [MMKV](https://github.com/Tencent/MMKV) (Tencent's key-value store) on-device. Sleep data is keyed by `{babyId}{date}-v2` with JSON values containing the day's events. The binary format stores entries as:

```
[key bytes] [varint length] [varint length] [JSON value]
```

Two serialization formats exist across backup versions:
- **Escaped JSON**: `"{\"allLogs\":[...]}"` (quoted string with escaped content)
- **Raw JSON**: `{"data":{"allLogs":[...]}}` (direct JSON)

The script reads all versioned backup snapshots to maximize date coverage, deduplicating by date (later entries override earlier ones).

### API Fetch

The Napper app authenticates via JWT (RS256) tokens stored in the MMKV auth file. The token file contains a history of rotations — the most recent valid token is near the end (MMKV is append-only).

Key endpoint: `GET /logs-between-days/{babyId}/{startDate}/{endDate}` returns all events in a date range.

### Nara Baby (Bonus)

If you also used Nara Baby, `extract_nara.py` pulls what's available locally (profile, config, last-tracked entries). Nara stores full history in Firebase — only snapshots are in the local backup.

## Data Dictionary

### napper_daily (CSV / SQLite)

| Column | Type | Description |
|--------|------|-------------|
| date | TEXT | YYYY-MM-DD |
| wake_time | TEXT | HH:MM local time |
| nap_start | TEXT | HH:MM |
| nap_end | TEXT | HH:MM |
| nap_duration_min | REAL | Nap length in minutes |
| nap_skipped | BOOL | Nap was skipped |
| bedtime | TEXT | HH:MM |
| how_baby_slept | TEXT | Sleep method (e.g. "SWING") |

### napper_events (CSV / SQLite)

| Column | Type | Description |
|--------|------|-------------|
| date | TEXT | YYYY-MM-DD |
| event_type | TEXT | WOKE_UP, NAP, BED_TIME, NIGHT_WAKING, BOTTLE, NURSING, MEDICINE |
| start | TEXT | ISO timestamp with timezone |
| end | TEXT | ISO timestamp with timezone |
| duration_min | REAL | Duration in minutes |
| skipped | BOOL | Event was marked skipped |
| comment | TEXT | User comment |
| created_by | TEXT | User ID who logged it |

## Limitations

- Auth tokens expire after ~30 days — re-extract from a fresh backup if needed
- The refresh token (valid ~1 year) could be used for auto-renewal, but that's not implemented
- Napper could change their API at any time
- Local MMKV extraction only captures what's in the rolling cache

## Other Baby Apps

| App | Local Data Available | Notes |
|-----|---------------------|-------|
| **Napper** | Full history via API; partial via MMKV | This project |
| **Nara Baby** | Config + last-track snapshots | Full history is Firebase server-side |
| **Nanit** | Encrypted locally | Not extractable without their API |
| **Huckleberry** | None | Entirely server-side |

## License

MIT
