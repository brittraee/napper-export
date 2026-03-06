#!/usr/bin/env python3
"""Find file hashes for Napper in an iMazing backup.

Queries the Manifest.db to find the SHA-1 hashes needed for config.json.
Run this first to populate your config.
"""

import json
import os
import sqlite3
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

BACKUP_BASE = os.path.expanduser(
    "~/Library/Application Support/iMazing/Backups"
)


def find_device() -> str | None:
    """Find the first device ID in the backup directory."""
    backup_dir = Path(BACKUP_BASE)
    for d in sorted(backup_dir.iterdir()):
        if d.is_dir() and d.name[0].isdigit():
            return d.name
    return None


def query_manifest(device_id: str) -> dict:
    """Query Manifest.db for Napper file hashes."""
    manifest = Path(BACKUP_BASE) / device_id / "Manifest.db"
    if not manifest.exists():
        print(f"Manifest.db not found at {manifest}")
        return {}

    conn = sqlite3.connect(manifest)

    queries = {
        "napper_query_hash": (
            "SELECT fileID FROM Files WHERE domain='AppDomain-com.niceguys.napper' "
            "AND relativePath='Documents/mmkv/query'"
        ),
        "napper_babies_hash": (
            "SELECT fileID FROM Files WHERE domain='AppDomain-com.niceguys.napper' "
            "AND relativePath='Documents/mmkv/babies'"
        ),
        "napper_auth_hash": (
            "SELECT fileID FROM Files WHERE domain='AppDomain-com.niceguys.napper' "
            "AND relativePath='Documents/mmkv/auth'"
        ),
    }

    results = {}
    for key, sql in queries.items():
        row = conn.execute(sql).fetchone()
        if row:
            results[key] = row[0]
            print(f"  {key}: {row[0]}")
        else:
            print(f"  {key}: not found")

    conn.close()
    return results


def find_baby_id(device_id: str, babies_hash: str) -> str | None:
    """Extract baby ID from the Napper babies MMKV file."""
    import re
    path = Path(BACKUP_BASE) / device_id / babies_hash[:2] / babies_hash
    if not path.exists():
        return None

    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")

    for match in re.finditer(r'\[{.*?}\]', text, re.DOTALL):
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                for item in parsed:
                    if "id" in item and "name" in item:
                        print(f"  Found baby: {item['name']} (id: {item['id']})")
                        return item["id"]
        except (json.JSONDecodeError, RecursionError):
            continue
    return None


def main():
    device_id = find_device()
    if not device_id:
        print("No device found in backup directory.")
        print(f"Expected backups at: {BACKUP_BASE}")
        return

    print(f"Device: {device_id}\n")
    print("Looking up file hashes...")
    hashes = query_manifest(device_id)

    if not hashes:
        return

    baby_id = None
    if "napper_babies_hash" in hashes:
        print("\nLooking up baby ID...")
        baby_id = find_baby_id(device_id, hashes["napper_babies_hash"])

    config = {"device_id": device_id}
    if baby_id:
        config["baby_id"] = baby_id
    config.update(hashes)

    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"\nConfig saved to {CONFIG_PATH}")


if __name__ == "__main__":
    main()
