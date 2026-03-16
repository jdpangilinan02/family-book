"""
Inbound email webhook — Envelope API.

POST /api/inbound/envelope

Receives forwarded emails to family@martin.fm, extracts photos from
attachments, matches sender email to Person, creates Moments.

HMAC signature verification via X-Envelope-Signature header.
"""

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbound"])


class EnvelopeAttachment(BaseModel):
    filename: str
    content_type: str
    url: str


class EnvelopePayload(BaseModel):
    sender: str = ""  # Envelope uses 'from' but that's a Python keyword
    subject: str = ""
    text_body: str = ""
    attachments: list[EnvelopeAttachment] = []


ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm",
}


@router.post("/api/inbound/envelope")
async def envelope_webhook(request: Request):
    """Receive inbound email from Envelope."""
    settings = get_settings()
    secret = settings.ENVELOPE_WEBHOOK_SECRET

    if not secret:
        raise HTTPException(status_code=500, detail="Webhook not configured")

    # Verify HMAC signature
    body = await request.body()
    signature = request.headers.get("X-Envelope-Signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    payload = await request.json()
    sender_email = payload.get("from", payload.get("sender", ""))
    subject = payload.get("subject", "")
    text_body = payload.get("text_body", "")
    attachments = payload.get("attachments", [])

    logger.info(
        "Inbound email from=%s subject=%s attachments=%d",
        sender_email, subject, len(attachments),
    )

    # Download and save attachments
    saved_files = []
    async with httpx.AsyncClient(timeout=30) as http:
        for att in attachments:
            content_type = att.get("content_type", "")
            if content_type not in ALLOWED_ATTACHMENT_TYPES:
                continue

            url = att.get("url", "")
            if not url:
                continue

            try:
                resp = await http.get(url)
                resp.raise_for_status()
                content = resp.content

                file_hash = hashlib.sha256(content).hexdigest()
                ext = _ext_from_mime(content_type)
                filename = f"email_{file_hash[:16]}{ext}"

                media_dir = os.path.join(settings.DATA_DIR, "media")
                os.makedirs(media_dir, exist_ok=True)
                file_path = os.path.join(media_dir, filename)

                with open(file_path, "wb") as f:
                    f.write(content)

                saved_files.append({
                    "filename": filename,
                    "file_hash": file_hash,
                    "content_type": content_type,
                    "size": len(content),
                })
                logger.info("Saved email attachment: %s (%d bytes)", filename, len(content))
            except Exception:
                logger.exception("Failed to download attachment: %s", att.get("filename"))

    # NOTE: Person matching (sender_email → Person.contact_email) and
    # Media + Moment record creation is a Phase 2 merge point.
    # Files are saved to data/media/ for Phase 2 to pick up.

    return {
        "status": "ok",
        "sender": sender_email,
        "attachments_saved": len(saved_files),
        "files": saved_files,
    }


def _ext_from_mime(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
    }.get(content_type, ".bin")
