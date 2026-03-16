import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import get_settings
from app.database import get_db
from app.models.media import Media
from app.models.person import Person
from app.services.media_service import save_media_file, ALLOWED_MIME_TYPES

router = APIRouter(prefix="/api/media", tags=["media"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    person_id: str = Form(...),
    caption: str | None = Form(None),
    current_user: Person = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Upload a media file. Deduplicates by SHA-256 hash."""
    if not file.content_type or file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    # Verify person exists
    result = await db.execute(select(Person).where(Person.id == person_id))
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=400, detail="Person not found")

    file_data = await file.read()

    try:
        media, is_duplicate = await save_media_file(
            db=db,
            file_data=file_data,
            filename=file.filename or "upload",
            mime_type=file.content_type,
            person_id=person_id,
            uploaded_by=current_user.id,
            caption=caption,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": media.id,
        "file_path": media.file_path,
        "media_type": media.media_type,
        "mime_type": media.mime_type,
        "width": media.width,
        "height": media.height,
        "file_size_bytes": media.file_size_bytes,
        "file_hash": media.file_hash,
        "caption": media.caption,
        "is_duplicate": is_duplicate,
        "created_at": str(media.created_at),
    }


@router.get("/{media_id}")
async def get_media_metadata(
    media_id: str,
    current_user: Person = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get media metadata."""
    result = await db.execute(select(Media).where(Media.id == media_id))
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    return {
        "id": media.id,
        "person_id": media.person_id,
        "file_path": media.file_path,
        "original_filename": media.original_filename,
        "media_type": media.media_type,
        "mime_type": media.mime_type,
        "width": media.width,
        "height": media.height,
        "file_size_bytes": media.file_size_bytes,
        "file_hash": media.file_hash,
        "caption": media.caption,
        "source": media.source,
        "uploaded_by": media.uploaded_by,
        "created_at": str(media.created_at),
    }


@router.get("/{media_id}/file")
async def serve_media_file(
    media_id: str,
    current_user: Person = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Serve the actual media file through an authenticated endpoint."""
    result = await db.execute(select(Media).where(Media.id == media_id))
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    if not media.file_path:
        raise HTTPException(status_code=404, detail="No file associated with this media")

    settings = get_settings()
    file_path = os.path.join(settings.DATA_DIR, "media", media.file_path)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=file_path,
        media_type=media.mime_type,
        filename=media.original_filename,
    )


@router.get("/{media_id}/thumbnail")
async def serve_thumbnail(
    media_id: str,
    current_user: Person = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Serve a thumbnail for image media."""
    result = await db.execute(select(Media).where(Media.id == media_id))
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    settings = get_settings()
    thumb_path = os.path.join(settings.DATA_DIR, "media", "thumbnails", f"{media.id}.jpg")

    if not os.path.isfile(thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return FileResponse(path=thumb_path, media_type="image/jpeg")


@router.get("", response_model=list)
async def list_media_for_person(
    person_id: str = Query(...),
    current_user: Person = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all media for a given person."""
    result = await db.execute(
        select(Media)
        .where(Media.person_id == person_id)
        .order_by(Media.created_at.desc())
    )
    media_list = result.scalars().all()
    return [
        {
            "id": m.id,
            "media_type": m.media_type,
            "mime_type": m.mime_type,
            "caption": m.caption,
            "file_hash": m.file_hash,
            "created_at": str(m.created_at),
        }
        for m in media_list
    ]
