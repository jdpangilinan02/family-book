"""
PWA routes — service worker registration, share target endpoint.

POST /api/share — receives shared photos from mobile share sheet
"""

import hashlib
import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from app.auth import get_current_user
from app.config import get_settings
from app.models.person import Person

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pwa"])

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4", "video/webm"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/api/share")
async def share_target(
    title: str = Form(default=""),
    text: str = Form(default=""),
    media: UploadFile | None = File(default=None),
    current_user: Person | None = Depends(get_current_user),
):
    """Receive shared content from PWA share sheet.

    If not logged in, redirect to login with return_to.
    """
    if current_user is None:
        return RedirectResponse(url="/login?return_to=/api/share", status_code=302)

    if media is None:
        return RedirectResponse(url="/?toast=shared", status_code=302)

    # Validate file type
    if media.content_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {media.content_type}")

    # Read and validate size
    content = await media.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Dedup by hash
    file_hash = hashlib.sha256(content).hexdigest()

    settings = get_settings()
    media_dir = os.path.join(settings.DATA_DIR, "media")
    os.makedirs(media_dir, exist_ok=True)

    ext = _ext_from_content_type(media.content_type)
    filename = f"share_{file_hash[:16]}{ext}"
    file_path = os.path.join(media_dir, filename)

    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(
        "Share target: user=%s file=%s size=%d hash=%s",
        current_user.id[:8], filename, len(content), file_hash[:12],
    )

    # NOTE: Media + Moment record creation is handled by Phase 2 routes.
    # This saves the file and redirects. Phase 2 merge point: create Media + Moment
    # records here using the saved file at media/{filename}.

    return RedirectResponse(url="/?toast=shared", status_code=302)


def _ext_from_content_type(ct: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
    }.get(ct, ".bin")
