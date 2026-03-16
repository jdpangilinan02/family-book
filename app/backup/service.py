"""
Backup service — SQLite .backup API + media directory, retention, health check.
"""

import gzip
import logging
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

BACKUP_RETENTION_DAYS = 30


def run_backup() -> str:
    """Run a SQLite backup + compress. Returns backup file path."""
    settings = get_settings()
    data_dir = settings.DATA_DIR
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"family-{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_name)
    gz_path = f"{backup_path}.gz"

    # Use SQLite's backup API (safe for WAL mode)
    db_url = settings.DATABASE_URL
    db_path = db_url.replace("sqlite:///", "")

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    src.close()

    # Compress
    with open(backup_path, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(backup_path)

    logger.info("Backup created: %s", gz_path)
    _cleanup_old_backups(backup_dir)
    return gz_path


def create_download_zip() -> str:
    """Create a .zip containing latest backup + media directory. Returns zip path."""
    settings = get_settings()
    data_dir = settings.DATA_DIR
    backup_dir = os.path.join(data_dir, "backups")

    # Find latest backup
    backups = sorted(Path(backup_dir).glob("family-*.db.gz"), reverse=True)
    if not backups:
        # Run a fresh backup
        run_backup()
        backups = sorted(Path(backup_dir).glob("family-*.db.gz"), reverse=True)

    zip_path = os.path.join(backup_dir, "family-book-backup.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add latest DB backup
        if backups:
            zf.write(str(backups[0]), f"db/{backups[0].name}")

        # Add media files
        media_dir = os.path.join(data_dir, "media")
        if os.path.isdir(media_dir):
            for root, _dirs, files in os.walk(media_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, data_dir)
                    zf.write(fpath, arcname)

    return zip_path


def get_backup_health() -> dict:
    """Return backup freshness info for health check."""
    settings = get_settings()
    backup_dir = os.path.join(settings.DATA_DIR, "backups")
    backups = sorted(Path(backup_dir).glob("family-*.db.gz"), reverse=True)

    if not backups:
        return {"last_backup": None, "backup_count": 0, "fresh": False}

    latest = backups[0]
    mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600

    return {
        "last_backup": mtime.isoformat(),
        "backup_count": len(backups),
        "fresh": age_hours < 25,  # less than 25 hours old
        "latest_file": latest.name,
        "latest_size_bytes": latest.stat().st_size,
    }


def _cleanup_old_backups(backup_dir: str) -> None:
    """Remove backups older than retention period."""
    now = datetime.now(timezone.utc)
    for f in Path(backup_dir).glob("family-*.db.gz"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        age_days = (now - mtime).days
        if age_days > BACKUP_RETENTION_DAYS:
            f.unlink()
            logger.info("Removed old backup: %s (%d days old)", f.name, age_days)
