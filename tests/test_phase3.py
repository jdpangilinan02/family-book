"""
Tests for Phase 3 — infrastructure, integration, deployment.

Covers: i18n, backup, security headers, rate limiting, PWA, email webhook,
Matrix client/handler.
"""

import gzip
import hashlib
import hmac
import json
import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base


@pytest_asyncio.fixture
async def fresh_client():
    """A test client with a fresh app instance (includes middleware + new routes)."""
    from app.main import create_app
    from app.database import get_db

    fresh_app = create_app()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    def pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    sa_event.listens_for(engine.sync_engine, "connect")(pragmas)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sf() as session:
        async def override():
            yield session

        fresh_app.dependency_overrides[get_db] = override
        transport = ASGITransport(app=fresh_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        fresh_app.dependency_overrides.clear()

    await engine.dispose()


# ─── i18n ────────────────────────────────────────────────────────────────


class TestI18n:
    def test_load_translations(self):
        from app.i18n import load_translations, get_translations

        load_translations()

        en = get_translations("en")
        assert en["nav"]["tree"] == "Family Tree"
        assert en["app"]["name"] == "Family Book"

        ru = get_translations("ru")
        assert ru["nav"]["tree"] == "Семейное Древо"

        es = get_translations("es")
        assert es["nav"]["tree"] == "Árbol Familiar"

    def test_t_function(self):
        from app.i18n import load_translations, t

        load_translations()
        assert t("nav.tree", "en") == "Family Tree"
        assert t("nav.tree", "ru") == "Семейное Древо"
        assert t("nav.tree", "es") == "Árbol Familiar"
        assert t("nav.tree", "xx") == "Family Tree"  # fallback to en
        assert t("nonexistent.key", "en") == "nonexistent.key"  # missing → key itself

    def test_relationship_terms(self):
        from app.i18n import load_translations, rel_term

        load_translations()
        assert rel_term("mother", "en") == "Mother"
        assert rel_term("mother", "ru") == "мама"
        assert rel_term("mother", "es") == "Madre"
        assert rel_term("maternal_grandmother", "ru") == "бабушка по маме"
        assert rel_term("paternal_grandfather", "es") == "Abuelo paterno"

    def test_all_locales_have_same_keys(self):
        from app.i18n import load_translations, get_translations

        load_translations()
        en_keys = _collect_keys(get_translations("en"))
        ru_keys = _collect_keys(get_translations("ru"))
        es_keys = _collect_keys(get_translations("es"))

        assert en_keys == ru_keys, f"ru diff: {en_keys.symmetric_difference(ru_keys)}"
        assert en_keys == es_keys, f"es diff: {en_keys.symmetric_difference(es_keys)}"


def _collect_keys(d: dict, prefix: str = "") -> set:
    keys = set()
    for k, v in d.items():
        full = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            keys.update(_collect_keys(v, full))
        else:
            keys.add(full)
    return keys


# ─── Backup ──────────────────────────────────────────────────────────────


class TestBackup:
    def test_run_backup(self, tmp_path):
        from unittest.mock import patch
        import sqlite3

        db_path = tmp_path / "family.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        (tmp_path / "backups").mkdir()

        class MockSettings:
            DATA_DIR = str(tmp_path)
            DATABASE_URL = f"sqlite:///{db_path}"

        with patch("app.backup.service.get_settings", return_value=MockSettings()):
            from app.backup.service import run_backup, get_backup_health

            gz_path = run_backup()
            assert os.path.exists(gz_path)
            assert gz_path.endswith(".gz")

            with gzip.open(gz_path, "rb") as f:
                data = f.read()
            assert len(data) > 0

            health = get_backup_health()
            assert health["backup_count"] >= 1
            assert health["fresh"] is True


# ─── Security headers ────────────────────────────────────────────────────


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_csp_header(self, fresh_client: AsyncClient):
        resp = await fresh_client.get("/health")
        assert resp.status_code == 200
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_x_content_type_options(self, fresh_client: AsyncClient):
        resp = await fresh_client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, fresh_client: AsyncClient):
        resp = await fresh_client.get("/health")
        assert resp.headers.get("x-frame-options") == "DENY"


# ─── Rate limiting ───────────────────────────────────────────────────────


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_backup_rate_limit(self, fresh_client: AsyncClient):
        """Backup endpoint rate limited to 2/hour. All return 401 (no auth)
        but the third should return 429 before auth check."""
        r1 = await fresh_client.post("/api/admin/backup")
        r2 = await fresh_client.post("/api/admin/backup")
        r3 = await fresh_client.post("/api/admin/backup")
        assert r3.status_code == 429


# ─── Envelope webhook ────────────────────────────────────────────────────


class TestEnvelopeWebhook:
    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self, fresh_client: AsyncClient):
        resp = await fresh_client.post(
            "/api/inbound/envelope",
            json={"from": "test@example.com", "subject": "test", "attachments": []},
        )
        assert resp.status_code in (401, 500)

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, fresh_client: AsyncClient):
        resp = await fresh_client.post(
            "/api/inbound/envelope",
            json={"from": "test@example.com"},
            headers={"X-Envelope-Signature": "invalid"},
        )
        assert resp.status_code in (401, 500)

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self, fresh_client: AsyncClient):
        from unittest.mock import patch

        secret = "test-webhook-secret"

        class MockSettings:
            ENVELOPE_WEBHOOK_SECRET = secret
            DATA_DIR = tempfile.mkdtemp()
            SECRET_KEY = "test"
            FERNET_KEY = "test"
            BASE_URL = "http://localhost:8000"

        body = json.dumps({
            "from": "test@example.com",
            "subject": "Family photos",
            "text_body": "Here are some photos!",
            "attachments": [],
        }).encode()

        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch("app.inbound.routes.get_settings", return_value=MockSettings()):
            resp = await fresh_client.post(
                "/api/inbound/envelope",
                content=body,
                headers={
                    "X-Envelope-Signature": sig,
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["attachments_saved"] == 0


# ─── PWA / Share target ─────────────────────────────────────────────────


class TestPWA:
    @pytest.mark.asyncio
    async def test_manifest_served(self, fresh_client: AsyncClient):
        resp = await fresh_client.get("/static/manifest.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Family Book"
        assert "share_target" in data

    @pytest.mark.asyncio
    async def test_service_worker_served(self, fresh_client: AsyncClient):
        resp = await fresh_client.get("/static/sw.js")
        assert resp.status_code == 200
        assert "family-book-v1" in resp.text

    @pytest.mark.asyncio
    async def test_share_unauthenticated_redirects(self, fresh_client: AsyncClient):
        resp = await fresh_client.post("/api/share", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")


# ─── Matrix client unit tests ───────────────────────────────────────────


class TestMatrixHandler:
    def test_event_timestamp_extraction(self):
        from app.matrix.handler import _event_timestamp
        from datetime import timezone

        event = {"origin_server_ts": 1700000000000}
        ts = _event_timestamp(event)
        assert ts.tzinfo == timezone.utc
        assert ts.year == 2023

        ts2 = _event_timestamp({})
        assert ts2.tzinfo == timezone.utc

    def test_ext_from_mime(self):
        from app.matrix.handler import _ext_from_mime

        assert _ext_from_mime("image/jpeg") == ".jpg"
        assert _ext_from_mime("video/mp4") == ".mp4"
        assert _ext_from_mime("application/octet-stream") == ".bin"


class TestMatrixClient:
    def test_create_matrix_client_unconfigured(self):
        from app.matrix.client import create_matrix_client

        client = create_matrix_client()
        assert client is None
