# napper-export

Export your child's complete sleep data from the [Napper](https://getnapper.com) app.

Napper doesn't offer a data export feature. This project extracts your sleep data through two methods:

1. **Local backup extraction** — Parse Napper's MMKV cache from an iOS backup (limited to recently cached days)
2. **API fetch** — Use your own auth token to pull complete history from Napper's API

## Why

I wanted a portable copy of my kid's sleep data — 3 years of wake times, naps, bedtimes, night wakings. The app stores everything server-side with no export option. GDPR data requests went unanswered (bounced by Apple's Hide My Email relay). So I built this.

The local backup approach only recovered ~45 days out of 1,000+ because Napper's MMKV cache rolls over every 7-10 days. The API approach recovered everything.

## What You Get

```
processed/
  napper_daily.csv     One row per day (wake time, nap, bedtime)
  napper_events.csv    One row per event (all categories)
sleep.db               SQLite database
raw/
  napper_api/          Complete JSON from API (organized by month)
  napper/              MMKV extraction (partial, for reference)
```

### Sample Output

**napper_daily.csv**
```
date,wake_time,nap_start,nap_end,nap_duration_min,nap_skipped,bedtime,how_baby_slept,wake_time_tz,nap_start_tz,nap_end_tz,bedtime_tz
2024-06-15,07:23,13:10,14:45,95.0,False,21:30,,08:23,14:10,15:45,22:30
2024-06-16,06:55,12:40,14:20,100.0,False,22:00,SWING,07:55,13:40,15:20,23:00
```

**napper_events.csv**
```
date,event_type,start_time,end_time,duration_min,skipped,start_time_tz,end_time_tz
2024-06-15,WOKE_UP,07:23,,,False,08:23,
2024-06-15,NAP,13:10,14:45,95.0,False,14:10,15:45
2024-06-15,BED_TIME,21:30,,,False,22:30,
```

## Quick Start

### Prerequisites

- macOS with Python 3.10+
- [iMazing](https://imazing.com) with at least one completed backup
- An active Napper account

### Dependencies

```bash
pip install protobuf  # Only needed for MMKV extraction
```

All other dependencies are standard library (`json`, `sqlite3`, `csv`, `urllib`).

### Setup

```bash
git clone https://github.com/brittraee/napper-export.git
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

## Timezone Normalization

If you moved time zones during your tracking period, you can normalize all clock times to a single timezone. Add a `timezone` field to your `config.json`:

```json
{
  "timezone": "America/Chicago"
}
```

This adds `_tz` columns alongside the original local times. Uses standard [IANA timezone names](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) (e.g. `America/New_York`, `America/Los_Angeles`, `Europe/London`). If omitted, no normalization is applied and only the original local times are included.

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

## Data Dictionary

### napper_daily (CSV / SQLite)

| Column | Type | Description |
|--------|------|-------------|
| date | TEXT | YYYY-MM-DD |
| wake_time | TEXT | HH:MM original local time |
| nap_start | TEXT | HH:MM |
| nap_end | TEXT | HH:MM |
| nap_duration_min | REAL | Nap length in minutes |
| nap_skipped | BOOL | Nap was skipped |
| bedtime | TEXT | HH:MM |
| how_baby_slept | TEXT | Sleep method (e.g. "SWING") |
| *_tz | TEXT | HH:MM in configured timezone (if set) |

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
| *_tz | TEXT | HH:MM in configured timezone (if set) |

## Privacy

This repo contains **code only** — no personal data. The `.gitignore` excludes:
- `config.json` (contains your device/baby IDs)
- `raw/` (API responses with timestamps)
- `processed/` (generated CSVs)
- `*.db` (SQLite database)

If you fork this repo, double-check that your `.gitignore` is working before pushing.

## Home Assistant Integration

A custom component is included to expose Napper sleep data as sensors in Home Assistant.

### Installation

1. Copy `custom_components/napper/` into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration** and search for "Napper"
4. Enter your API token (from `extract_token.py`) and baby ID (from `config.json`)

### Sensors

The integration creates these sensors (polled every 5 minutes):

| Sensor | Description |
|--------|-------------|
| Wake Time | Today's wake-up time (HH:MM) |
| Nap Start / End | Nap window |
| Nap Duration | Nap length in minutes |
| Nap Skipped | Whether nap was skipped |
| Bedtime | Bedtime (falls back to yesterday if not set today) |
| How Baby Slept | Sleep method (e.g. SWING) |
| Night Wakings | Count of night wakings today |
| Last Event Time / Type | Most recent logged event |
| Events Today | Total events logged today |

### Token Refresh

Auth tokens expire after ~30 days. When yours expires, re-extract from a fresh iMazing backup and update the integration config.

## Limitations

- Auth tokens expire after ~30 days — re-extract from a fresh backup if needed
- The refresh token (valid ~1 year) could be used for auto-renewal, but that's not implemented
- Napper could change their API at any time
- Local MMKV extraction only captures what's in the rolling cache

## Other Baby Apps

| App | Local Data Available | Notes |
|-----|---------------------|-------|
| **Napper** | Full history via API; partial via MMKV | This project |
| **Nanit** | Encrypted locally | Not extractable without their API |
| **Huckleberry** | None | Entirely server-side |

## License

MIT
