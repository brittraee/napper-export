#!/usr/bin/env python3
"""Extract Napper sleep data from iMazing backup MMKV files.

Reads all versioned backup snapshots + main backup to get the widest date range.

MMKV format in these backups:
- Keys like: {babyId}{date}-v2
- Between key and value: 4 binary bytes (two varints for value length)
- Value: quoted escaped JSON string like "{\"allLogs\":[...]}"

Each date key appears twice in the file:
1. As a real MMKV key-value pair (bytes after key end with 0x22 0x7b = '"{')
2. Embedded inside a larger JSON value (bytes after key start with 0x5c 0x22 = '\\"')

We distinguish these by checking the raw bytes after the key match.
"""

import json
import os
import re
from collections import OrderedDict
from pathlib import Path

CONFIG = json.load(open(Path(__file__).parent / "config.json"))

BACKUP_BASE = os.path.expanduser(
    "~/Library/Application Support/iMazing/Backups"
)
DEVICE_ID = CONFIG["device_id"]
MAIN_BACKUP = Path(BACKUP_BASE) / DEVICE_ID
VERSIONS_DIR = Path(BACKUP_BASE) / "iMazing.Versions" / "Versions" / DEVICE_ID

NAPPER_QUERY_HASH = CONFIG["napper_query_hash"]
NAPPER_BABIES_HASH = CONFIG["napper_babies_hash"]

BABY_ID = CONFIG["baby_id"]
BABY_ID_BYTES = BABY_ID.encode("utf-8")

OUTPUT_DIR = Path(__file__).parent / "raw" / "napper"


def hash_path(base: Path, hash_id: str) -> Path:
    return base / hash_id[:2] / hash_id


def extract_escaped_json_from_bytes(data: bytes, start: int) -> dict | list | None:
    """Extract escaped JSON string starting at position start (which should be 0x22 '"').

    Format: "{\"key\":\"value\"...}" — a quoted string with escaped JSON inside.
    We find the closing unescaped quote and then unescape the content.
    """
    if start >= len(data) or data[start:start+1] != b'"':
        return None

    text = data[start:].decode("utf-8", errors="replace")
    i = 1  # skip opening quote
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            i += 2
            continue
        if text[i] == '"':
            escaped = text[1:i]
            unescaped = escaped.replace('\\"', '"').replace('\\\\', '\\')
            try:
                return json.loads(unescaped)
            except (json.JSONDecodeError, RecursionError):
                return None
        i += 1
    return None


def extract_raw_json_from_bytes(data: bytes, start: int) -> dict | list | None:
    """Extract a raw (unescaped) JSON object/array from bytes.

    Decodes from the start position to avoid offset misalignment caused by
    multi-byte replacement characters when decoding the full binary file.
    """
    if start >= len(data) or data[start:start+1] not in (b'{', b'['):
        return None
    text = data[start:].decode("utf-8", errors="replace")
    if not text or text[0] not in ('{', '['):
        return None
    bracket = text[0]
    close = '}' if bracket == '{' else ']'
    depth = 0
    in_string = False
    escape = False
    for i in range(min(500000, len(text))):
        c = text[i]
        if escape:
            escape = False
        elif c == '\\' and in_string:
            escape = True
        elif c == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if c == bracket:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[:i + 1])
                    except (json.JSONDecodeError, RecursionError):
                        return None
    return None


def extract_from_file(filepath: Path) -> dict:
    """Extract all sleep data from a single MMKV file."""
    data = filepath.read_bytes()

    date_log_pattern = re.compile(
        re.escape(BABY_ID_BYTES) + rb'(\d{4}-\d{2}-\d{2})-v2'
    )
    stats_pattern = re.compile(
        re.escape(BABY_ID_BYTES) + rb'_SLEEP_STATS_(\d{4}-\d{2}-\d{2})'
    )

    sleep_logs = {}
    sleep_stats = {}

    for pattern, target in [(date_log_pattern, sleep_logs), (stats_pattern, sleep_stats)]:
        for match in pattern.finditer(data):
            date = match.group(1).decode("utf-8")
            pos = match.end()
            after = data[pos:pos + 10]

            # Skip embedded references (inside JSON strings)
            # Embedded refs start with 0x5c 0x22 (\")
            if len(after) >= 2 and after[0:2] == b'\\\"':
                continue

            # Find the quote that starts the JSON value
            # Pattern: binary varint bytes + 0x22 (") + escaped JSON
            quote_pos = None
            for j in range(min(20, len(after))):
                if after[j:j+1] == b'"':
                    quote_pos = pos + j
                    break

            # Try to find JSON value in the next ~20 bytes
            # Two formats:
            # 1. Escaped: varint bytes + '"' + '{\\"...\\"}'  (versioned backups)
            # 2. Raw:     varint bytes + '{' or '['           (main backup)
            parsed = None
            for j in range(min(20, len(after))):
                b = after[j:j+1]
                if b == b'"' and j + 1 < len(after) and after[j+1:j+2] in (b'{', b'['):
                    # Escaped JSON string
                    parsed = extract_escaped_json_from_bytes(data, pos + j)
                    break
                elif b in (b'{', b'['):
                    # Raw JSON
                    parsed = extract_raw_json_from_bytes(data, pos + j)
                    break

            if parsed is not None:
                target[date] = parsed

    return {"sleep_logs": sleep_logs, "sleep_stats": sleep_stats}


def normalize_logs(raw_logs: dict) -> dict:
    """Normalize to date -> [events]."""
    normalized = {}
    for date, entry in raw_logs.items():
        logs = []
        if isinstance(entry, dict):
            if "allLogs" in entry:
                logs = entry["allLogs"]
            elif "data" in entry:
                d = entry["data"]
                if isinstance(d, dict) and "allLogs" in d:
                    logs = d["allLogs"]
        if logs:
            normalized[date] = logs
    return normalized


def normalize_stats(raw_stats: dict) -> dict:
    """Normalize to date -> [day_summaries]."""
    normalized = {}
    for date, entry in raw_stats.items():
        stats = []
        if isinstance(entry, list):
            stats = entry
        elif isinstance(entry, dict):
            if "data" in entry and isinstance(entry["data"], list):
                stats = entry["data"]
        if stats:
            normalized[date] = stats
    return normalized


def extract_baby_profile(data: bytes) -> dict:
    """Extract baby profile from MMKV babies file."""
    text = data.decode("utf-8", errors="replace")
    for match in re.finditer(r'\[{.*?}\]', text, re.DOTALL):
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list) and any("name" in item for item in parsed):
                return {"babies": parsed}
        except (json.JSONDecodeError, RecursionError):
            continue
    return {}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sources = []
    if VERSIONS_DIR.exists():
        for snap in sorted(VERSIONS_DIR.iterdir()):
            if snap.is_dir() and snap.name[0].isdigit():
                sources.append(("versioned:" + snap.name, snap))
    if MAIN_BACKUP.exists():
        sources.append(("main", MAIN_BACKUP))

    print(f"Found {len(sources)} backup sources")

    all_logs = {}
    all_stats = {}

    for label, base in sources:
        query_file = hash_path(base, NAPPER_QUERY_HASH)
        if not query_file.exists():
            print(f"  {label}: query file not found, skipping")
            continue

        size_mb = query_file.stat().st_size / 1024 / 1024
        result = extract_from_file(query_file)

        logs = normalize_logs(result["sleep_logs"])
        stats = normalize_stats(result["sleep_stats"])

        print(f"  {label}: {len(logs)} log days, {len(stats)} stat entries [{size_mb:.1f} MB]")

        # Merge — later entries override earlier
        all_logs.update(logs)
        all_stats.update(stats)

    all_logs = OrderedDict(sorted(all_logs.items()))
    all_stats = OrderedDict(sorted(all_stats.items()))

    # Write sleep logs
    logs_path = OUTPUT_DIR / "sleep_logs.json"
    with open(logs_path, "w") as f:
        json.dump(all_logs, f, indent=2)
    print(f"\nSleep logs: {len(all_logs)} days -> {logs_path}")
    if all_logs:
        dates = list(all_logs.keys())
        print(f"  Date range: {dates[0]} to {dates[-1]}")

    # Write sleep stats
    stats_path = OUTPUT_DIR / "sleep_stats.json"
    with open(stats_path, "w") as f:
        json.dump(all_stats, f, indent=2)
    print(f"Sleep stats: {len(all_stats)} entries -> {stats_path}")

    # Write flattened events
    all_events = []
    for date, logs in all_logs.items():
        for log in logs:
            event = {
                "date": date,
                "category": log.get("category"),
                "start": log.get("start"),
                "end": log.get("end"),
                "skipped": log.get("skipped", False),
                "comment": log.get("comment", ""),
                "created_by": log.get("createdByUserId", ""),
                "id": log.get("id", ""),
                "how_baby_slept": log.get("howBabySlept", ""),
                "pauses": log.get("pauses", []),
            }
            all_events.append(event)

    events_path = OUTPUT_DIR / "sleep_events.json"
    with open(events_path, "w") as f:
        json.dump(all_events, f, indent=2)
    print(f"Sleep events: {len(all_events)} total events -> {events_path}")

    # Baby profile
    for label, base in reversed(sources):
        babies_file = hash_path(base, NAPPER_BABIES_HASH)
        if babies_file.exists():
            profile = extract_baby_profile(babies_file.read_bytes())
            if profile:
                profile_path = OUTPUT_DIR / "baby_profile.json"
                with open(profile_path, "w") as f:
                    json.dump(profile, f, indent=2)
                print(f"Baby profile -> {profile_path}")
                break


if __name__ == "__main__":
    main()
