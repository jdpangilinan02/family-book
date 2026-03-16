"""
Matrix event handler — converts bridged messages into Moment + Media records.

Idempotency: Matrix event IDs stored in ExternalIdentity(provider='matrix_event')
to prevent duplicate creation on reconnection.
"""

import hashlib
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imports import ExternalIdentity
from app.models.media import Media, MediaSource, MediaType
from app.models.moments import Moment, MomentKind, MomentSource

logger = logging.getLogger(__name__)

# Map Matrix msgtype to our MediaType
MSGTYPE_MAP = {
    "m.image": MediaType.image,
    "m.video": MediaType.video,
    "m.audio": MediaType.audio,
}

# Map mime prefix to MediaType fallback
MIME_PREFIX_MAP = {
    "image/": MediaType.image,
    "video/": MediaType.video,
    "audio/": MediaType.audio,
}


class MatrixEventHandler:
    """Processes Matrix events and persists them as Family Book data."""

    def __init__(self, session_factory, matrix_client, data_dir: str):
        self.session_factory = session_factory
        self.matrix_client = matrix_client
        self.data_dir = data_dir

    async def handle_event(self, event_type: str, event: dict) -> None:
        """Dispatch to specific handler based on event type."""
        if event_type == "m.room.message":
            await self._handle_message(event)
        elif event_type == "m.reaction":
            await self._handle_reaction(event)

    async def _handle_message(self, event: dict) -> None:
        event_id = event.get("event_id")
        if not event_id:
            return

        content = event.get("content", {})
        msgtype = content.get("msgtype", "")
        sender = event.get("sender", "")

        async with self.session_factory() as session:
            # Idempotency check
            if await self._event_already_processed(session, event_id):
                return

            # Resolve sender → Person
            person_id = await self._resolve_person(session, sender)
            if not person_id:
                logger.warning("Matrix sender %s not mapped to a Person, skipping", sender)
                return

            timestamp = _event_timestamp(event)

            if msgtype in MSGTYPE_MAP:
                await self._ingest_media_message(
                    session, event_id, content, msgtype, person_id, timestamp
                )
            elif msgtype == "m.text":
                await self._ingest_text_message(
                    session, event_id, content, person_id, timestamp
                )

            # Record event as processed
            session.add(ExternalIdentity(
                person_id=person_id,
                provider="matrix_event",
                external_id=event_id,
            ))
            await session.commit()

    async def _ingest_media_message(
        self,
        session: AsyncSession,
        event_id: str,
        content: dict,
        msgtype: str,
        person_id: str,
        timestamp: datetime,
    ) -> None:
        mxc_url = content.get("url", "")
        if not mxc_url:
            return

        # Download media from Matrix
        media_bytes, content_type = await self.matrix_client.download_media(mxc_url)

        # Dedup by SHA-256 hash
        file_hash = hashlib.sha256(media_bytes).hexdigest()
        existing = await session.execute(
            select(Media).where(Media.file_hash == file_hash)
        )
        if existing.scalar_one_or_none():
            logger.info("Skipping duplicate media (hash=%s)", file_hash[:12])
            return

        # Save file
        media_dir = os.path.join(self.data_dir, "media")
        os.makedirs(media_dir, exist_ok=True)
        ext = _ext_from_mime(content_type)
        filename = f"matrix_{file_hash[:16]}{ext}"
        file_path = os.path.join(media_dir, filename)
        with open(file_path, "wb") as f:
            f.write(media_bytes)

        media_type = MSGTYPE_MAP.get(msgtype, MediaType.image)
        info = content.get("info", {})
        caption = content.get("body", "")

        # Create Media record
        media = Media(
            person_id=person_id,
            file_path=f"media/{filename}",
            original_filename=content.get("body"),
            media_type=media_type.value,
            mime_type=content_type,
            width=info.get("w"),
            height=info.get("h"),
            file_size_bytes=len(media_bytes),
            file_hash=file_hash,
            caption=caption if caption != filename else None,
            source=MediaSource.matrix.value,
        )
        session.add(media)
        await session.flush()

        # Create Moment
        kind = MomentKind.photo if media_type == MediaType.image else MomentKind.video
        moment = Moment(
            person_id=person_id,
            kind=kind.value,
            body=caption if caption != filename else None,
            occurred_at=timestamp,
            source="matrix",
            posted_by=person_id,
        )
        moment.media_ids = [media.id]
        session.add(moment)

        logger.info("Ingested Matrix media: %s → Media %s, Moment %s",
                     event_id, media.id[:8], moment.id[:8])

    async def _ingest_text_message(
        self,
        session: AsyncSession,
        event_id: str,
        content: dict,
        person_id: str,
        timestamp: datetime,
    ) -> None:
        body = content.get("body", "").strip()
        if not body:
            return

        moment = Moment(
            person_id=person_id,
            kind=MomentKind.text.value,
            body=body,
            occurred_at=timestamp,
            source="matrix",
            posted_by=person_id,
        )
        session.add(moment)
        logger.info("Ingested Matrix text message from event %s", event_id)

    async def _handle_reaction(self, event: dict) -> None:
        """Convert m.reaction → MomentReaction (stubbed for Phase 2 merge)."""
        # Reactions require matching the m.relates_to.event_id to a Moment
        # via its ExternalIdentity(provider=matrix_event). This needs the
        # MomentReaction model which Phase 2 routes expose. Log for now.
        event_id = event.get("event_id", "?")
        relates = event.get("content", {}).get("m.relates_to", {})
        logger.debug("Matrix reaction %s on %s (deferred to Phase 2 merge)",
                      event_id, relates.get("event_id"))

    async def _event_already_processed(self, session: AsyncSession, event_id: str) -> bool:
        result = await session.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "matrix_event",
                ExternalIdentity.external_id == event_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _resolve_person(self, session: AsyncSession, matrix_user_id: str) -> str | None:
        """Look up Person by ExternalIdentity(provider=matrix, external_id=@user:server)."""
        result = await session.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "matrix",
                ExternalIdentity.external_id == matrix_user_id,
            )
        )
        identity = result.scalar_one_or_none()
        return identity.person_id if identity else None


def _event_timestamp(event: dict) -> datetime:
    """Extract timestamp from Matrix event, fallback to now."""
    origin_ts = event.get("origin_server_ts")
    if origin_ts:
        return datetime.fromtimestamp(origin_ts / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _ext_from_mime(content_type: str) -> str:
    """Best-effort file extension from MIME type."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
    }
    return mapping.get(content_type, ".bin")
