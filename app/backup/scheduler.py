"""
In-app backup scheduler — runs daily at 03:00 UTC.
Uses a simple threading.Timer approach (no heavy dependencies).
Serves as supplement to Docker cron for Railway deployments.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.backup.service import run_backup

logger = logging.getLogger(__name__)

_timer: threading.Timer | None = None
_running = False


def _next_3am_utc() -> float:
    """Seconds until next 03:00 UTC."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _run_and_reschedule() -> None:
    """Execute backup and schedule next run."""
    global _timer
    if not _running:
        return
    try:
        run_backup()
    except Exception:
        logger.exception("Scheduled backup failed")

    # Schedule next run
    _timer = threading.Timer(_next_3am_utc(), _run_and_reschedule)
    _timer.daemon = True
    _timer.start()


def start_backup_scheduler() -> None:
    """Start the daily backup scheduler."""
    global _timer, _running
    _running = True
    delay = _next_3am_utc()
    _timer = threading.Timer(delay, _run_and_reschedule)
    _timer.daemon = True
    _timer.start()
    next_run = datetime.now(timezone.utc) + timedelta(seconds=delay)
    logger.info("Backup scheduler started. Next backup at %s", next_run.isoformat())


def stop_backup_scheduler() -> None:
    """Stop the backup scheduler."""
    global _timer, _running
    _running = False
    if _timer:
        _timer.cancel()
        _timer = None
    logger.info("Backup scheduler stopped")
