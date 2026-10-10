"""Locate the iOS backup folder used by the extraction scripts.

Works with iMazing backups and with standard Finder / iTunes backups, since
both use the same layout (Manifest.db plus SHA-1-named files in two-character
subfolders).

Resolution order:
1. NAPPER_BACKUP_PATH environment variable
2. "backup_path" in config.json
3. First default location that exists (iMazing, then Finder/iTunes)
"""

import json
import os
import plistlib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_LOCATIONS = [
    # iMazing (macOS)
    "~/Library/Application Support/iMazing/Backups",
    # Finder / iTunes (macOS)
    "~/Library/Application Support/MobileSync/Backup",
    # iTunes / Apple Devices (Windows)
    "~/Apple/MobileSync/Backup",
    "~/AppData/Roaming/Apple Computer/MobileSync/Backup",
]


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def get_backup_base(config: dict | None = None) -> Path:
    """Return the folder that contains one subfolder per device backup."""
    env = os.environ.get("NAPPER_BACKUP_PATH")
    if env:
        return Path(os.path.expanduser(env))

    cfg = config if config is not None else _load_config()
    if cfg.get("backup_path"):
        return Path(os.path.expanduser(cfg["backup_path"]))

    for loc in DEFAULT_LOCATIONS:
        p = Path(os.path.expanduser(loc))
        if p.exists():
            return p

    return Path(os.path.expanduser(DEFAULT_LOCATIONS[0]))


def is_encrypted(device_dir: Path) -> bool:
    """True if the backup in device_dir is encrypted (Finder/iTunes setting)."""
    plist = device_dir / "Manifest.plist"
    if not plist.exists():
        return False
    try:
        with open(plist, "rb") as f:
            return bool(plistlib.load(f).get("IsEncrypted", False))
    except Exception:
        return False


ENCRYPTED_HELP = (
    "This backup is encrypted, so its files can't be read directly.\n"
    "Either make an unencrypted backup (Finder > your iPhone > uncheck\n"
    "'Encrypt local backup'), or use iMazing, which can decrypt backups."
)
