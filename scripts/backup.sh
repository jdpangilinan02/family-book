#!/bin/sh
# Daily backup script — called by cron inside Docker container
# Also callable manually: ./scripts/backup.sh

set -e

DATA_DIR="${DATA_DIR:-/data}"
DB_PATH="${DATA_DIR}/family.db"
BACKUP_DIR="${DATA_DIR}/backups"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_NAME="family-${TIMESTAMP}.db"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

if [ ! -f "${DB_PATH}" ]; then
    echo "ERROR: Database not found at ${DB_PATH}"
    exit 1
fi

# Use SQLite backup API (WAL-safe)
sqlite3 "${DB_PATH}" ".backup ${BACKUP_DIR}/${BACKUP_NAME}"

# Compress
gzip "${BACKUP_DIR}/${BACKUP_NAME}"

echo "Backup created: ${BACKUP_DIR}/${BACKUP_NAME}.gz"

# Cleanup old backups
find "${BACKUP_DIR}" -name "family-*.db.gz" -mtime "+${RETENTION_DAYS}" -delete

echo "Backup complete at $(date -u)"
