import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person, AccountState
from app.models.auth import UserSession, Invite, MagicLinkToken
from app.services import auth_service
from app.services.auth_service import (
    create_session,
    validate_session,
    delete_session,
    create_invite,
    claim_invite,
    create_magic_link,
    validate_magic_link,
    _hash_token,
)


@pytest.mark.asyncio
async def test_create_and_validate_session(seeded_db: AsyncSession):
    token = await create_session(
        seeded_db,
        person_id="alex-000-0000-0000-000000000002",
        auth_method="magic_link",
    )
    await seeded_db.commit()

    person = await validate_session(seeded_db, token)
    assert person is not None
    assert person.first_name == "Alex"


@pytest.mark.asyncio
async def test_invalid_session_returns_none(seeded_db: AsyncSession):
    person = await validate_session(seeded_db, "bogus-token")
    assert person is None


@pytest.mark.asyncio
async def test_delete_session(seeded_db: AsyncSession):
    token = await create_session(
        seeded_db,
        person_id="alex-000-0000-0000-000000000002",
        auth_method="magic_link",
    )
    await seeded_db.commit()

    await delete_session(seeded_db, token)
    await seeded_db.commit()

    person = await validate_session(seeded_db, token)
    assert person is None


@pytest.mark.asyncio
async def test_expired_session_rejected(seeded_db: AsyncSession):
    token = await create_session(
        seeded_db,
        person_id="alex-000-0000-0000-000000000002",
        auth_method="magic_link",
    )
    await seeded_db.commit()

    # Manually expire the session
    token_hash = _hash_token(token)
    result = await seeded_db.execute(
        select(UserSession).where(UserSession.token_hash == token_hash)
    )
    session = result.scalar_one()
    session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await seeded_db.commit()

    person = await validate_session(seeded_db, token)
    assert person is None


@pytest.mark.asyncio
async def test_suspended_user_session_rejected(seeded_db: AsyncSession):
    # Suspend Alex
    result = await seeded_db.execute(
        select(Person).where(Person.id == "alex-000-0000-0000-000000000002")
    )
    alex = result.scalar_one()
    alex.account_state = AccountState.suspended.value
    await seeded_db.commit()

    token = await create_session(
        seeded_db,
        person_id="alex-000-0000-0000-000000000002",
        auth_method="magic_link",
    )
    await seeded_db.commit()

    person = await validate_session(seeded_db, token)
    assert person is None


@pytest.mark.asyncio
async def test_invite_create_and_claim(seeded_db: AsyncSession):
    invite = await create_invite(
        seeded_db,
        person_id="member-00-0000-0000-000000000005",
        created_by="alex-000-0000-0000-000000000002",
    )
    await seeded_db.commit()

    raw_token = getattr(invite, "raw_token", None)
    assert raw_token is not None

    result = await seeded_db.execute(select(Invite).where(Invite.id == invite.id))
    stored_invite = result.scalar_one()
    assert stored_invite.token == _hash_token(raw_token)
    assert stored_invite.claimed_at is None

    person = await claim_invite(seeded_db, raw_token)
    assert person is not None
    assert person.first_name == "Jane"

    # Can't claim twice
    person2 = await claim_invite(seeded_db, raw_token)
    assert person2 is None


@pytest.mark.asyncio
async def test_expired_invite_rejected(seeded_db: AsyncSession):
    invite = await create_invite(
        seeded_db,
        person_id="member-00-0000-0000-000000000005",
        created_by="alex-000-0000-0000-000000000002",
    )
    invite.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await seeded_db.commit()

    person = await claim_invite(seeded_db, getattr(invite, "raw_token"))
    assert person is None


@pytest.mark.asyncio
async def test_get_invite_route_accepts_raw_token_when_storage_is_hashed(
    client: AsyncClient,
    seeded_db: AsyncSession,
):
    invite = await create_invite(
        seeded_db,
        person_id="member-00-0000-0000-000000000005",
        created_by="alex-000-0000-0000-000000000002",
    )
    await seeded_db.commit()

    resp = await client.get(f"/invite/{getattr(invite, 'raw_token')}")

    assert resp.status_code == 200
    assert resp.json()["person_name"] == "Jane Rivera"


@pytest.mark.asyncio
async def test_magic_link_request_logs_only_redacted_token(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
):
    raw_token = "deadbeef" * 8
    monkeypatch.setattr(auth_service, "generate_magic_link_token", lambda: raw_token)

    with caplog.at_level(logging.INFO, logger="app.routes.auth_routes"):
        resp = await client.post("/auth/magic-link", json={"email": "alex@example.com"})

    assert resp.status_code == 200
    auth_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.routes.auth_routes"
    ]
    assert auth_logs
    assert any(f"{raw_token[:8]}..." in message for message in auth_logs)
    assert all(raw_token not in message for message in auth_logs)


@pytest.mark.asyncio
async def test_magic_link_create_and_validate(seeded_db: AsyncSession):
    token = await create_magic_link(seeded_db, "alex-000-0000-0000-000000000002")
    await seeded_db.commit()

    person = await validate_magic_link(seeded_db, token)
    assert person is not None
    assert person.first_name == "Alex"

    # Can't use twice
    person2 = await validate_magic_link(seeded_db, token)
    assert person2 is None


@pytest.mark.asyncio
async def test_expired_magic_link_rejected(seeded_db: AsyncSession):
    token = await create_magic_link(seeded_db, "alex-000-0000-0000-000000000002")
    await seeded_db.commit()

    # Expire the token
    token_hash = _hash_token(token)
    result = await seeded_db.execute(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash)
    )
    ml = result.scalar_one()
    ml.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await seeded_db.commit()

    person = await validate_magic_link(seeded_db, token)
    assert person is None


@pytest.mark.asyncio
async def test_magic_link_request_includes_safe_return_to_in_email(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    async def fake_send_magic_link_email(to_email: str, magic_link_url: str) -> bool:
        captured["to_email"] = to_email
        captured["magic_link_url"] = magic_link_url
        return True

    monkeypatch.setattr("app.routes.auth_routes.send_magic_link_email", fake_send_magic_link_email)

    resp = await client.post(
        "/auth/magic-link",
        json={"email": "alex@example.com", "return_to": "/trips/join/summer-2026"},
    )

    assert resp.status_code == 200
    assert captured["to_email"] == "alex@example.com"
    parsed = urlparse(captured["magic_link_url"])
    assert parsed.path.startswith("/auth/magic-link/")
    assert parse_qs(parsed.query) == {"return_to": ["/trips/join/summer-2026"]}


@pytest.mark.asyncio
async def test_magic_link_request_rejects_external_return_to_in_email(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    async def fake_send_magic_link_email(to_email: str, magic_link_url: str) -> bool:
        captured["magic_link_url"] = magic_link_url
        return True

    monkeypatch.setattr("app.routes.auth_routes.send_magic_link_email", fake_send_magic_link_email)

    resp = await client.post(
        "/auth/magic-link",
        json={"email": "alex@example.com", "return_to": "https://evil.example/phish"},
    )

    assert resp.status_code == 200
    parsed = urlparse(captured["magic_link_url"])
    assert parsed.path.startswith("/auth/magic-link/")
    assert parsed.query == ""


@pytest.mark.asyncio
async def test_verify_magic_link_redirects_into_app_and_sets_session_cookie(
    client: AsyncClient,
    seeded_db: AsyncSession,
):
    token = await create_magic_link(seeded_db, "alex-000-0000-0000-000000000002")
    await seeded_db.commit()

    resp = await client.get(
        f"/auth/magic-link/{token}?return_to=/tree",
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/tree"
    assert "session=" in resp.headers.get("set-cookie", "")

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Alex Rivera"


@pytest.mark.asyncio
async def test_verify_magic_link_expired_redirects_to_login(
    client: AsyncClient,
):
    resp = await client.get(
        "/auth/magic-link/bogus-token-that-does-not-exist",
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?error=expired"
