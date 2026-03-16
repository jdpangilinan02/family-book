import hashlib
import os
import uuid
from io import BytesIO

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.media import Media, MediaSource, MediaType

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/quicktime", "video/webm",
    "audio/opus", "audio/mp3", "audio/m4a", "audio/ogg",
}

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

MAX_SIZE_BY_CATEGORY = {
    "image": 10 * 1024 * 1024,      # 10 MB
    "video": 100 * 1024 * 1024,     # 100 MB
    "audio": 25 * 1024 * 1024,      # 25 MB
}

THUMBNAIL_SIZE = (400, 400)


def _category_for_mime(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "image"


def _media_type_for_mime(mime_type: str) -> str:
    if mime_type == "image/gif":
        return MediaType.gif.value
    if mime_type.startswith("image/"):
        return MediaType.image.value
    if mime_type.startswith("video/"):
        return MediaType.video.value
    if mime_type.startswith("audio/"):
        return MediaType.audio.value
    return MediaType.image.value


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_exif(data: bytes, mime_type: str) -> bytes:
    """Strip EXIF data from images for privacy."""
    if mime_type not in IMAGE_MIME_TYPES or mime_type == "image/gif":
        return data
    try:
        img = Image.open(BytesIO(data))
        clean = Image.new(img.mode, img.size)
        clean.paste(img)
        buf = BytesIO()
        fmt = "JPEG" if mime_type == "image/jpeg" else ("PNG" if mime_type == "image/png" else "WEBP")
        clean.save(buf, format=fmt, quality=90)
        return buf.getvalue()
    except Exception:
        return data


def generate_thumbnail(data: bytes, mime_type: str) -> bytes | None:
    """Generate a thumbnail for image files."""
    if mime_type not in IMAGE_MIME_TYPES:
        return None
    try:
        img = Image.open(BytesIO(data))
        img.thumbnail(THUMBNAIL_SIZE)
        # Strip EXIF from thumbnail too
        clean = Image.new(img.mode, img.size)
        clean.paste(img)
        buf = BytesIO()
        clean.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return None


def get_image_dimensions(data: bytes, mime_type: str) -> tuple[int | None, int | None]:
    if mime_type not in IMAGE_MIME_TYPES:
        return None, None
    try:
        img = Image.open(BytesIO(data))
        return img.width, img.height
    except Exception:
        return None, None


async def check_duplicate(db: AsyncSession, file_hash: str) -> Media | None:
    result = await db.execute(select(Media).where(Media.file_hash == file_hash))
    return result.scalar_one_or_none()


async def save_media_file(
    db: AsyncSession,
    file_data: bytes,
    filename: str,
    mime_type: str,
    person_id: str,
    uploaded_by: str,
    caption: str | None = None,
    data_dir: str | None = None,
) -> tuple[Media, bool]:
    """
    Save a media file. Returns (media, is_duplicate).
    If duplicate, returns the existing media record.
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported MIME type: {mime_type}")

    category = _category_for_mime(mime_type)
    max_size = MAX_SIZE_BY_CATEGORY[category]
    if len(file_data) > max_size:
        raise ValueError(f"File too large: {len(file_data)} bytes (max {max_size})")

    file_hash = compute_sha256(file_data)

    existing = await check_duplicate(db, file_hash)
    if existing:
        return existing, True

    # Strip EXIF from images
    clean_data = strip_exif(file_data, mime_type)

    if data_dir is None:
        data_dir = get_settings().DATA_DIR

    media_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    relative_path = f"{media_id}{ext}"

    media_dir = os.path.join(data_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    file_path = os.path.join(media_dir, relative_path)
    with open(file_path, "wb") as f:
        f.write(clean_data)

    # Generate thumbnail for images
    thumb_data = generate_thumbnail(clean_data, mime_type)
    if thumb_data:
        thumb_dir = os.path.join(media_dir, "thumbnails")
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, f"{media_id}.jpg")
        with open(thumb_path, "wb") as f:
            f.write(thumb_data)

    width, height = get_image_dimensions(file_data, mime_type)

    media = Media(
        id=media_id,
        person_id=person_id,
        file_path=relative_path,
        original_filename=filename,
        media_type=_media_type_for_mime(mime_type),
        mime_type=mime_type,
        width=width,
        height=height,
        file_size_bytes=len(clean_data),
        file_hash=file_hash,
        caption=caption,
        source=MediaSource.manual.value,
        uploaded_by=uploaded_by,
    )
    db.add(media)
    await db.flush()

    return media, False
