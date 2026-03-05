#!/usr/bin/env python3
"""Extract Nara Baby data from iMazing backup plist files.

Nara stores data in Firebase and only keeps config + last-track snapshots locally.
This preserves what's available: child profile, tracking config, and last entries.
"""

import json
import os
import plistlib
from pathlib import Path

CONFIG = json.load(open(Path(__file__).parent / "config.json"))

MAIN_BACKUP = Path(os.path.expanduser(
    "~/Library/Application Support/iMazing/Backups"
)) / CONFIG["device_id"]

NARA_APP_PLIST = CONFIG["nara_app_plist_hash"]
NARA_GROUP_PLIST = CONFIG["nara_group_plist_hash"]

OUTPUT_DIR = Path(__file__).parent / "raw" / "nara"


def hash_path(hash_id: str) -> Path:
    return MAIN_BACKUP / hash_id[:2] / hash_id


def parse_json_values(d: dict) -> dict:
    """Recursively parse JSON string values in a plist dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            # Try parsing as JSON
            try:
                parsed = json.loads(v)
                result[k] = parsed
            except (json.JSONDecodeError, ValueError):
                result[k] = v
        elif isinstance(v, dict):
            result[k] = parse_json_values(v)
        elif isinstance(v, bytes):
            # Try decoding binary plist data
            try:
                result[k] = plistlib.loads(v)
            except Exception:
                result[k] = v.hex()
        else:
            result[k] = v
    return result


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_data = {}

    for label, hash_id in [("app_prefs", NARA_APP_PLIST), ("group_prefs", NARA_GROUP_PLIST)]:
        filepath = hash_path(hash_id)
        if not filepath.exists():
            print(f"  {label}: file not found, skipping")
            continue

        with open(filepath, "rb") as f:
            try:
                plist = plistlib.load(f)
            except Exception as e:
                print(f"  {label}: failed to parse plist: {e}")
                continue

        parsed = parse_json_values(plist)
        all_data[label] = parsed
        print(f"  {label}: {len(parsed)} keys")

    if not all_data:
        print("No Nara data found")
        return

    # Extract child profile
    profile = {}
    app = all_data.get("app_prefs", {})
    group = all_data.get("group_prefs", {})

    # Child info from group prefs
    for key, val in group.items():
        if key.startswith("childz_"):
            profile["children"] = val

    # Last tracked activities
    last_tracks = {}
    for key, val in app.items():
        if "childzLastTrackz" in key:
            if isinstance(val, str):
                try:
                    last_tracks = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    last_tracks = {"raw": val}
            elif isinstance(val, dict):
                last_tracks = val

    # Config
    config = {}
    for key, val in app.items():
        if "familyUserConfig" in key or "familyChildz" in key:
            config[key] = val

    # Write outputs
    profile_path = OUTPUT_DIR / "profile.json"
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"Profile -> {profile_path}")

    tracks_path = OUTPUT_DIR / "last_tracks.json"
    with open(tracks_path, "w") as f:
        json.dump(last_tracks, f, indent=2)
    print(f"Last tracks -> {tracks_path}")

    config_path = OUTPUT_DIR / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config -> {config_path}")

    # Write full raw dump for preservation
    raw_path = OUTPUT_DIR / "full_dump.json"
    with open(raw_path, "w") as f:
        json.dump(all_data, f, indent=2, default=str)
    print(f"Full dump -> {raw_path}")


if __name__ == "__main__":
    main()
