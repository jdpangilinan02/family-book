"""Tests for Media API — upload, serve, dedup, auth gate, thumbnails."""
import os
import io

import pytest
from PIL import Image


def _make_test_image(width=100, height=100, fmt="JPEG") -> bytes:
    """Create a minimal test image with EXIF-like data."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_test_png(width=50, height=50) -> bytes:
    img = Image.new("RGBA", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestMediaUpload:
    """POST /api/media"""

    async def test_upload_requires_auth(self, client):
        resp = await client.post("/api/media", data={"person_id": "x"})
        assert resp.status_code == 401

    async def test_upload_image(self, admin_client, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        from app.config import Settings
        monkeypatch.setattr(
            "app.services.media_service.get_settings",
            lambda: Settings(
                SECRET_KEY="test", FERNET_KEY="dGVzdA==",
                DATA_DIR=str(tmp_path),
            ),
        )

        image_data = _make_test_image()
        resp = await admin_client.post(
            "/api/media",
            data={"person_id": "tyler-000-0000-0000-000000000002"},
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["media_type"] == "image"
        assert body["mime_type"] == "image/jpeg"
        assert body["file_hash"] is not None
        assert body["is_duplicate"] is False
        assert body["width"] == 100
        assert body["height"] == 100

    async def test_upload_rejects_unsupported_type(self, admin_client):
        resp = await admin_client.post(
            "/api/media",
            data={"person_id": "tyler-000-0000-0000-000000000002"},
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    async def test_upload_rejects_nonexistent_person(self, admin_client, tmp_path, monkeypatch):
        from app.config import Settings
        monkeypatch.setattr(
            "app.services.media_service.get_settings",
            lambda: Settings(
                SECRET_KEY="test", FERNET_KEY="dGVzdA==",
                DATA_DIR=str(tmp_path),
            ),
        )

        image_data = _make_test_image()
        resp = await admin_client.post(
            "/api/media",
            data={"person_id": "nonexistent-person-id"},
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        assert resp.status_code == 400
        assert "Person not found" in resp.json()["detail"]


class TestMediaDedup:
    """SHA-256 dedup on upload."""

    async def test_duplicate_returns_existing(self, admin_client, tmp_path, monkeypatch):
        from app.config import Settings
        monkeypatch.setattr(
            "app.services.media_service.get_settings",
            lambda: Settings(
                SECRET_KEY="test", FERNET_KEY="dGVzdA==",
                DATA_DIR=str(tmp_path),
            ),
        )

        image_data = _make_test_image()
        person_id = "tyler-000-0000-0000-000000000002"

        # First upload
        resp1 = await admin_client.post(
            "/api/media",
            data={"person_id": person_id},
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        assert resp1.status_code == 201
        first_id = resp1.json()["id"]

        # Same file again
        resp2 = await admin_client.post(
            "/api/media",
            data={"person_id": person_id},
            files={"file": ("test2.jpg", image_data, "image/jpeg")},
        )
        assert resp2.status_code == 201
        assert resp2.json()["is_duplicate"] is True
        assert resp2.json()["id"] == first_id


class TestMediaServing:
    """GET /api/media/{id}/file — auth-gated serving."""

    async def test_serve_requires_auth(self, client):
        resp = await client.get("/api/media/fake-id/file")
        assert resp.status_code == 401

    async def test_serve_file(self, admin_client, tmp_path, monkeypatch):
        from app.config import Settings
        settings = Settings(
            SECRET_KEY="test", FERNET_KEY="dGVzdA==",
            DATA_DIR=str(tmp_path),
        )
        monkeypatch.setattr("app.services.media_service.get_settings", lambda: settings)
        monkeypatch.setattr("app.routes.media.get_settings", lambda: settings)

        image_data = _make_test_image()
        resp = await admin_client.post(
            "/api/media",
            data={"person_id": "tyler-000-0000-0000-000000000002"},
            files={"file": ("photo.jpg", image_data, "image/jpeg")},
        )
        media_id = resp.json()["id"]

        # Serve file
        resp2 = await admin_client.get(f"/api/media/{media_id}/file")
        assert resp2.status_code == 200
        assert resp2.headers["content-type"] == "image/jpeg"
        assert len(resp2.content) > 0

    async def test_serve_nonexistent_returns_404(self, admin_client):
        resp = await admin_client.get("/api/media/nonexistent/file")
        assert resp.status_code == 404


class TestMediaThumbnails:
    """GET /api/media/{id}/thumbnail"""

    async def test_thumbnail_generated_for_images(self, admin_client, tmp_path, monkeypatch):
        from app.config import Settings
        settings = Settings(
            SECRET_KEY="test", FERNET_KEY="dGVzdA==",
            DATA_DIR=str(tmp_path),
        )
        monkeypatch.setattr("app.services.media_service.get_settings", lambda: settings)
        monkeypatch.setattr("app.routes.media.get_settings", lambda: settings)

        image_data = _make_test_image(width=800, height=600)
        resp = await admin_client.post(
            "/api/media",
            data={"person_id": "tyler-000-0000-0000-000000000002"},
            files={"file": ("big.jpg", image_data, "image/jpeg")},
        )
        media_id = resp.json()["id"]

        resp2 = await admin_client.get(f"/api/media/{media_id}/thumbnail")
        assert resp2.status_code == 200
        assert resp2.headers["content-type"] == "image/jpeg"

        # Thumbnail should be smaller than original
        assert len(resp2.content) < len(image_data)


class TestMediaMetadata:
    """GET /api/media/{id} and GET /api/media?person_id="""

    async def test_get_metadata(self, admin_client, tmp_path, monkeypatch):
        from app.config import Settings
        settings = Settings(
            SECRET_KEY="test", FERNET_KEY="dGVzdA==",
            DATA_DIR=str(tmp_path),
        )
        monkeypatch.setattr("app.services.media_service.get_settings", lambda: settings)

        image_data = _make_test_image()
        resp = await admin_client.post(
            "/api/media",
            data={
                "person_id": "tyler-000-0000-0000-000000000002",
                "caption": "Test caption",
            },
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        media_id = resp.json()["id"]

        resp2 = await admin_client.get(f"/api/media/{media_id}")
        assert resp2.status_code == 200
        body = resp2.json()
        assert body["caption"] == "Test caption"
        assert body["person_id"] == "tyler-000-0000-0000-000000000002"

    async def test_list_media_for_person(self, admin_client, tmp_path, monkeypatch):
        from app.config import Settings
        settings = Settings(
            SECRET_KEY="test", FERNET_KEY="dGVzdA==",
            DATA_DIR=str(tmp_path),
        )
        monkeypatch.setattr("app.services.media_service.get_settings", lambda: settings)

        person_id = "tyler-000-0000-0000-000000000002"
        image_data = _make_test_image()
        await admin_client.post(
            "/api/media",
            data={"person_id": person_id},
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )

        resp = await admin_client.get(f"/api/media?person_id={person_id}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
