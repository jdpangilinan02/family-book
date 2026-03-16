"""
Matrix bot client for Family Book.

Connects to Conduit homeserver, joins the family room, and listens for
m.room.message and m.reaction events. Media is downloaded and converted
to Moment + Media records.

This module is designed to run as a background asyncio task started
during FastAPI lifespan.
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Matrix event types we care about
EVENT_MESSAGE = "m.room.message"
EVENT_REACTION = "m.reaction"

# Message types we ingest
MEDIA_MSGTYPES = {"m.image", "m.video", "m.audio"}
TEXT_MSGTYPES = {"m.text"}


class MatrixClient:
    """Lightweight async Matrix client using httpx (no heavy SDK dependency)."""

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        password: str,
        family_room: str,
        data_dir: str,
    ):
        self.homeserver = homeserver.rstrip("/")
        self.user_id = user_id
        self.password = password
        self.family_room = family_room
        self.data_dir = data_dir
        self.access_token: str | None = None
        self.sync_token: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._running = False

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Login and begin the sync loop."""
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30, read=90))
        await self._login()
        await self._ensure_room_joined()
        self._running = True
        logger.info("Matrix client started as %s in room %s", self.user_id, self.family_room)

    async def stop(self) -> None:
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("Matrix client stopped")

    async def run_sync_loop(self, on_event) -> None:
        """Long-poll /sync and dispatch events to callback.

        on_event signature: async def on_event(event_type: str, event: dict) -> None
        """
        while self._running:
            try:
                events = await self._sync()
                for event_type, event in events:
                    try:
                        await on_event(event_type, event)
                    except Exception:
                        logger.exception("Error handling Matrix event %s", event.get("event_id"))
            except httpx.ReadTimeout:
                continue  # normal for long-poll
            except Exception:
                logger.exception("Matrix sync error, retrying in 5s")
                await asyncio.sleep(5)

    # -- auth -------------------------------------------------------------

    async def _login(self) -> None:
        resp = await self._http.post(
            f"{self.homeserver}/_matrix/client/v3/login",
            json={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": self.user_id},
                "password": self.password,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        logger.info("Logged in to Matrix as %s", data.get("user_id"))

    # -- room -------------------------------------------------------------

    async def _ensure_room_joined(self) -> None:
        resp = await self._http.post(
            f"{self.homeserver}/_matrix/client/v3/join/{self.family_room}",
            headers=self._auth_headers(),
        )
        if resp.status_code in (200, 409):  # 409 = already joined
            return
        resp.raise_for_status()

    # -- sync -------------------------------------------------------------

    async def _sync(self) -> list[tuple[str, dict]]:
        """Perform one /sync call. Returns list of (event_type, event) tuples."""
        params = {
            "timeout": "30000",
            "filter": '{"room":{"timeline":{"limit":50}}}',
        }
        if self.sync_token:
            params["since"] = self.sync_token

        resp = await self._http.get(
            f"{self.homeserver}/_matrix/client/v3/sync",
            params=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        self.sync_token = data.get("next_batch")

        events = []
        rooms = data.get("rooms", {}).get("join", {})
        room_data = rooms.get(self.family_room, {})
        timeline = room_data.get("timeline", {}).get("events", [])

        for event in timeline:
            event_type = event.get("type")
            if event_type in (EVENT_MESSAGE, EVENT_REACTION):
                events.append((event_type, event))

        return events

    # -- media download ---------------------------------------------------

    async def download_media(self, mxc_url: str) -> tuple[bytes, str]:
        """Download media from Matrix. Returns (content_bytes, content_type).

        mxc_url format: mxc://server/mediaId
        """
        if not mxc_url.startswith("mxc://"):
            raise ValueError(f"Invalid mxc URL: {mxc_url}")

        server_media = mxc_url[6:]  # strip "mxc://"
        resp = await self._http.get(
            f"{self.homeserver}/_matrix/media/v3/download/{server_media}",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "application/octet-stream")
        return resp.content, content_type

    # -- outbound ---------------------------------------------------------

    async def send_text(self, room_id: str, body: str) -> str | None:
        """Send a text message to a room. Returns event_id."""
        resp = await self._http.post(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/{EVENT_MESSAGE}",
            headers=self._auth_headers(),
            json={
                "msgtype": "m.text",
                "body": body,
            },
        )
        resp.raise_for_status()
        return resp.json().get("event_id")

    async def send_image(self, room_id: str, mxc_url: str, filename: str, body: str = "") -> str | None:
        """Send an image message to a room."""
        resp = await self._http.post(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/{EVENT_MESSAGE}",
            headers=self._auth_headers(),
            json={
                "msgtype": "m.image",
                "body": body or filename,
                "url": mxc_url,
                "info": {"mimetype": "image/jpeg"},
            },
        )
        resp.raise_for_status()
        return resp.json().get("event_id")

    # -- helpers ----------------------------------------------------------

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}


def create_matrix_client() -> MatrixClient | None:
    """Factory: returns MatrixClient if configured, else None."""
    settings = get_settings()
    homeserver = getattr(settings, "MATRIX_HOMESERVER", "")
    bot_user = getattr(settings, "MATRIX_BOT_USER", "")
    bot_pass = getattr(settings, "MATRIX_BOT_PASSWORD", "")
    family_room = getattr(settings, "MATRIX_FAMILY_ROOM", "")

    if not all([homeserver, bot_user, bot_pass, family_room]):
        return None

    return MatrixClient(
        homeserver=homeserver,
        user_id=bot_user,
        password=bot_pass,
        family_room=family_room,
        data_dir=settings.DATA_DIR,
    )
