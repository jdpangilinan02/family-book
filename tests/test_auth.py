import logging
import pytest
from datetime import datetime, timedelta, timezone
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
        person_id="tyler-000-0000-0000-000000000002",
        auth_method="magic_link",
    )
    await seeded_db.commit()

    person = await validate_session(seeded_db, token)
    assert person is not None
    assert person.first_name == "Tyler"


@pytest.mark.asyncio
async def test_invalid_session_returns_none(seeded_db: AsyncSession):
    person = await validate_session(seeded_db, "bogus-token")
    assert person is None


@pytest.mark.asyncio
async def test_delete_session(seeded_db: AsyncSession):
    token = await create_session(
        seeded_db,
        person_id="tyler-000-0000-0000-000000000002",
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
        person_id="tyler-000-0000-0000-000000000002",
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
    # Suspend Tyler
    result = await seeded_db.execute(
        select(Person).where(Person.id == "tyler-000-0000-0000-000000000002")
    )
    tyler = result.scalar_one()
    tyler.account_state = AccountState.suspended.value
    await seeded_db.commit()

    token = await create_session(
        seeded_db,
        person_id="tyler-000-0000-0000-000000000002",
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
        created_by="tyler-000-0000-0000-000000000002",
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
        created_by="tyler-000-0000-0000-000000000002",
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
        created_by="tyler-000-0000-0000-000000000002",
    )
    await seeded_db.commit()

    resp = await client.get(f"/invite/{getattr(invite, 'raw_token')}")

    assert resp.status_code == 200
    assert resp.json()["person_name"] == "Jane Martin"


@pytest.mark.asyncio
async def test_magic_link_request_logs_only_redacted_token(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
):
    raw_token = "deadbeef" * 8
    monkeypatch.setattr(auth_service, "generate_magic_link_token", lambda: raw_token)

    with caplog.at_level(logging.INFO, logger="app.routes.auth_routes"):
        resp = await client.post("/auth/magic-link", json={"email": "tyler@example.com"})

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
    token = await create_magic_link(seeded_db, "tyler-000-0000-0000-000000000002")
    await seeded_db.commit()

    person = await validate_magic_link(seeded_db, token)
    assert person is not None
    assert person.first_name == "Tyler"

    # Can't use twice
    person2 = await validate_magic_link(seeded_db, token)
    assert person2 is None


@pytest.mark.asyncio
async def test_expired_magic_link_rejected(seeded_db: AsyncSession):
    token = await create_magic_link(seeded_db, "tyler-000-0000-0000-000000000002")
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
