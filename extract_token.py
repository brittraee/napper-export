#!/usr/bin/env python3
"""Extract Napper auth token from iMazing backup.

Reads the MMKV auth file from the backup and extracts the most recent
valid JWT ID token. MMKV is append-only, so the newest (valid) token
is near the end of the file.

Saves the token to /tmp/napper_token.txt for use by fetch_napper_api.py.
"""

import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path

CONFIG = json.load(open(Path(__file__).parent / "config.json"))

BACKUP_BASE = os.path.expanduser(
    "~/Library/Application Support/iMazing/Backups"
)
DEVICE_ID = CONFIG["device_id"]

# Find the auth MMKV hash from Manifest.db
# Domain: AppDomain-com.niceguys.napper
# RelativePath: Documents/mmkv/auth
# You can find this by running:
#   sqlite3 /path/to/Manifest.db \
#     "SELECT fileID FROM Files WHERE relativePath='Documents/mmkv/auth'
#      AND domain='AppDomain-com.niceguys.napper'"
AUTH_HASH = CONFIG.get("napper_auth_hash", "")

TOKEN_OUT = Path("/tmp/napper_token.txt")


def find_auth_file() -> Path | None:
    """Find the auth MMKV file in the backup."""
    if AUTH_HASH:
        path = Path(BACKUP_BASE) / DEVICE_ID / AUTH_HASH[:2] / AUTH_HASH
        if path.exists():
            return path

    # Try to find it via Manifest.db
    manifest = Path(BACKUP_BASE) / DEVICE_ID / "Manifest.db"
    if manifest.exists():
        import sqlite3
        conn = sqlite3.connect(manifest)
        row = conn.execute(
            "SELECT fileID FROM Files WHERE relativePath='Documents/mmkv/auth' "
            "AND domain='AppDomain-com.niceguys.napper'"
        ).fetchone()
        conn.close()
        if row:
            h = row[0]
            path = Path(BACKUP_BASE) / DEVICE_ID / h[:2] / h
            if path.exists():
                print(f"Found auth file via Manifest.db: {h}")
                return path

    return None


def main():
    auth_file = find_auth_file()
    if not auth_file:
        print("Auth MMKV file not found. Set napper_auth_hash in config.json")
        print("or ensure Manifest.db is accessible.")
        return

    data = auth_file.read_bytes()
    print(f"Auth file: {auth_file} ({len(data)} bytes)")

    # Find all JWT tokens (header.payload.signature)
    best_token = None
    best_exp = 0

    for m in re.finditer(b"AUTH_ID_TOKEN", data):
        chunk = data[m.start():m.start() + 3000]
        jwt_match = re.search(
            rb"(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
            chunk,
        )
        if not jwt_match:
            continue

        token = jwt_match.group(1).decode()
        parts = token.split(".")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        exp = payload.get("exp", 0)
        iat = payload.get("iat", 0)
        exp_dt = datetime.fromtimestamp(exp)
        iat_dt = datetime.fromtimestamp(iat)

        now = datetime.now().timestamp()
        status = "VALID" if exp > now else "expired"
        print(f"  Token issued={iat_dt:%Y-%m-%d} expires={exp_dt:%Y-%m-%d} [{status}]")

        if exp > best_exp:
            best_exp = exp
            best_token = token

    if not best_token:
        print("\nNo tokens found.")
        return

    if best_exp < datetime.now().timestamp():
        print(f"\nBest token is expired. You may need a fresh backup after opening the app.")
        return

    TOKEN_OUT.write_text(best_token)
    exp_dt = datetime.fromtimestamp(best_exp)
    print(f"\nSaved valid token to {TOKEN_OUT}")
    print(f"Expires: {exp_dt:%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
