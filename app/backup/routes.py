"""
Backup admin API routes.

POST /api/admin/backup       — trigger immediate backup
GET  /api/admin/backup/download — download latest backup as .zip
GET  /api/admin/backup/status  — backup health info
"""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from app.auth import require_admin
from app.backup.service import create_download_zip, get_backup_health, run_backup
from app.models.person import Person

router = APIRouter(prefix="/api/admin/backup", tags=["backup"])


@router.post("")
async def trigger_backup(admin: Person = Depends(require_admin)) -> JSONResponse:
    """Trigger an immediate backup."""
    path = run_backup()
    return JSONResponse({"status": "ok", "path": path})


@router.get("/download")
async def download_backup(admin: Person = Depends(require_admin)) -> FileResponse:
    """Download latest backup as .zip (DB + media)."""
    zip_path = create_download_zip()
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="family-book-backup.zip",
    )


@router.get("/status")
async def backup_status(admin: Person = Depends(require_admin)) -> JSONResponse:
    """Return backup freshness info."""
    return JSONResponse(get_backup_health())
