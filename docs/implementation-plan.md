# Family Book — Phase 1 (MVP) Implementation Plan

**Date:** 2026-03-15
**Status:** Planning
**Scope:** Repo setup, data model + SQLite, Facebook OAuth, manual tree entry (admin), basic tree visualization, person cards, mobile-first responsive design, Railway deployment.

**Out of scope for Phase 1:** Facebook data export ingestion, WhatsApp sync, graph-distance privacy enforcement, world map, birthday calendar, i18n, PWA, ActivityPub.

---

## 1. Directory & File Structure

```
family-book/
├── SPEC.md
├── CLAUDE.md
├── .gitignore
├── .env.example                # Template for required env vars
├── pyproject.toml              # Python project config (deps, scripts, metadata)
├── Dockerfile                  # Multi-stage build for Railway
├── .dockerignore
├── alembic.ini                 # DB migration config
├── migrations/
│   ├── env.py                  # Alembic environment setup
│   └── versions/
│       └── 001_initial_schema.py   # Initial tables
├── seed.json                   # Tyler's initial family tree data
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app factory, CORS, lifespan, mount static
│   ├── config.py               # Settings via pydantic-settings (env vars)
│   ├── database.py             # SQLite engine, session factory, get_db dependency
│   ├── models.py               # SQLAlchemy ORM models
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── auth.py                 # Facebook OAuth logic, token encryption
│   ├── graph.py                # BFS relationship computation, labeling
│   ├── dependencies.py         # FastAPI deps (current_user, require_admin)
│   ├── seed.py                 # CLI script to seed initial family data
│   └── routers/
│       ├── __init__.py
│       ├── auth.py             # /auth/* endpoints (login, callback, logout, me)
│       ├── persons.py          # /api/persons/* CRUD endpoints
│       ├── relationships.py    # /api/relationships/* CRUD endpoints
│       ├── tree.py             # /api/tree (full tree data for visualization)
│       └── health.py           # /health endpoint for Railway
├── templates/
│   ├── base.html               # Shared HTML shell (head, nav, scripts)
│   ├── landing.html            # Public landing page
│   ├── tree.html               # Tree visualization page
│   ├── person.html             # Person detail/card page
│   └── admin.html              # Admin panel (CRUD forms)
├── static/
│   ├── css/
│   │   └── style.css           # All styles (mobile-first, single file for MVP)
│   ├── js/
│   │   ├── vendor/
│   │   │   └── d3.v7.min.js    # Self-hosted D3.js (no CDN, no third-party scripts)
│   │   ├── tree.js             # D3.js tree rendering + interaction
│   │   ├── person-card.js      # Person card component behavior
│   │   ├── admin.js            # Admin CRUD form handling
│   │   └── auth.js             # OAuth redirect + session management
│   └── img/
│       ├── placeholder.svg     # Default avatar for persons without photos
│       └── logo.svg            # Family Book logo/wordmark
├── tests/
│   ├── conftest.py             # Fixtures (test DB, test client, seed data)
│   ├── test_auth.py            # OAuth flow tests (mocked Facebook)
│   ├── test_persons.py         # Person CRUD tests
│   ├── test_relationships.py   # Relationship CRUD tests
│   ├── test_graph.py           # BFS, relationship labeling tests
│   └── test_tree.py            # Tree data assembly tests
└── docs/
    └── implementation-plan.md  # This file
```

### File Purposes

| File | Purpose |
|------|---------|
| `app/main.py` | Creates FastAPI instance, registers routers, mounts `/static`, configures Jinja2 templates, defines lifespan (DB init on startup, migrations) |
| `app/config.py` | Single `Settings` class reading all env vars with defaults. Validates required vars at startup. |
| `app/database.py` | Creates `aiosqlite` engine via SQLAlchemy async. Provides `get_db` async generator for DI. Sets WAL mode + foreign keys on every connection. |
| `app/models.py` | All ORM models: `Person`, `Relationship`, `ImportedAsset`, `FacebookToken`, `Session` |
| `app/schemas.py` | Pydantic models for every API request/response. Strict validation. |
| `app/auth.py` | `FacebookOAuth` class: builds auth URL, exchanges code for token, fetches profile, downloads photo. Fernet encrypt/decrypt for tokens. |
| `app/graph.py` | `FamilyGraph` class: loads relationships, runs BFS, computes relationship labels (English only for Phase 1). |
| `app/dependencies.py` | `get_current_user`: extracts + validates session from cookie. `require_admin`: raises 403 if not admin. |
| `app/seed.py` | CLI script: reads `seed.json`, upserts persons + relationships. Idempotent. |
| `seed.json` | Initial family tree for Tyler to fill in manually. Human-friendly (names, not UUIDs). |

---

## 2. Database Schema (SQLite)

SQLite via SQLAlchemy async + aiosqlite. All UUIDs stored as TEXT. Dates stored as TEXT in ISO 8601 format.

```sql
-- ============================================================
-- persons
-- ============================================================
CREATE TABLE persons (
    id TEXT PRIMARY KEY,                          -- UUID4 as hex string
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    patronymic TEXT,                              -- Russian/Arabic naming (store now, display Phase 4)
    birth_last_name TEXT,                          -- Maiden name
    nickname TEXT,
    gender TEXT,                                   -- "male", "female", NULL. For relationship labels.
    photo_url TEXT,                                -- Relative path to stored photo
    birth_date TEXT,                               -- ISO 8601 (YYYY-MM-DD), nullable
    death_date TEXT,                               -- ISO 8601, nullable. Presence = memorial.
    location TEXT,                                 -- "Madrid, Spain" free text
    country_code TEXT,                             -- ISO 3166-1 alpha-2 ("CA", "RU", "ES")
    languages TEXT,                                -- JSON array: ["en", "ru", "es"]
    bio TEXT,
    contact_whatsapp TEXT,                         -- Phone with country code
    contact_telegram TEXT,                         -- Username without @
    contact_signal TEXT,                           -- Phone with country code
    contact_email TEXT,
    facebook_id TEXT UNIQUE,                       -- From OAuth, for deduplication
    is_admin INTEGER NOT NULL DEFAULT 0,           -- 1 = admin (Tyler, Yuliya)
    manually_added INTEGER NOT NULL DEFAULT 1,     -- 1 = added by admin, 0 = via OAuth
    branch TEXT,                                   -- "martin", "semesock", "maternal" for color coding
    privacy_layer_override INTEGER,                -- Admin override (NULL = computed). Phase 3 logic, column present now.
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_persons_facebook_id ON persons(facebook_id);
CREATE INDEX idx_persons_country_code ON persons(country_code);

-- ============================================================
-- relationships
-- Direction convention:
--   parent_child: person_a_id = PARENT, person_b_id = CHILD. Always.
--   spouse/ex_spouse/sibling: person_a_id < person_b_id (lexicographic) to prevent duplicates.
-- ============================================================
CREATE TABLE relationships (
    id TEXT PRIMARY KEY,                           -- UUID4
    person_a_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    person_b_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL CHECK (
        relationship_type IN ('parent_child', 'spouse', 'sibling', 'ex_spouse')
    ),
    start_date TEXT,                               -- Marriage date, birth date, etc.
    end_date TEXT,                                 -- Divorce date, death date
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dissolved')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(person_a_id, person_b_id, relationship_type)
);

CREATE INDEX idx_rel_person_a ON relationships(person_a_id);
CREATE INDEX idx_rel_person_b ON relationships(person_b_id);

-- ============================================================
-- facebook_tokens (encrypted at rest)
-- ============================================================
CREATE TABLE facebook_tokens (
    person_id TEXT PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
    access_token_encrypted TEXT NOT NULL,           -- Fernet-encrypted long-lived token
    token_expires_at TEXT,                          -- ISO 8601 datetime
    scopes TEXT,                                    -- JSON array of granted scopes
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- sessions (server-side session storage)
-- ============================================================
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                            -- UUID4, stored in HttpOnly cookie
    person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,                       -- 30 days from creation
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_sessions_person ON sessions(person_id);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- ============================================================
-- imported_assets (Phase 1: profile_info from OAuth only. Photos/exports in Phase 2.)
-- ============================================================
CREATE TABLE imported_assets (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (
        source IN ('facebook_oauth', 'facebook_export', 'whatsapp', 'manual')
    ),
    asset_type TEXT NOT NULL CHECK (
        asset_type IN ('photo', 'post', 'profile_info', 'friends_list')
    ),
    data TEXT NOT NULL,                             -- JSON blob
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_assets_person ON imported_assets(person_id);
```

### Schema Design Decisions

| Decision | Rationale |
|----------|-----------|
| Contacts as flat columns (not JSON) | Simpler queries, no JSON path extraction for MVP |
| `gender TEXT` column | Required for gendered labels ("Father" vs "Mother"). Nullable — defaults to gender-neutral. |
| `branch TEXT` column | Admin-assigned. Used for tree color coding. Children inherit closest parent's branch. |
| `privacy_layer_override INTEGER` | NULL = compute from graph (Phase 3). Integer = admin-forced layer. Column exists now to avoid migration later. |
| `parent_child` directionality | Always `person_a = parent`, `person_b = child`. Critical invariant — enforced in application code. |
| Symmetric relationship normalization | For `spouse`/`sibling`/`ex_spouse`, always store `min(a,b)` as `person_a_id`. Enforced in app code. |
| Server-side sessions (not JWT) | Sessions can be revoked immediately. No JWT refresh complexity. |

### Required SQLite PRAGMAs (set on every connection)

```python
# In database.py — connection event listener
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")       # Write-Ahead Log for concurrent reads
    cursor.execute("PRAGMA foreign_keys=ON")         # FK enforcement (OFF by default!)
    cursor.execute("PRAGMA busy_timeout=5000")       # 5s wait on write lock
    cursor.close()
```

---

## 3. Facebook OAuth Flow

### 3.1 Prerequisites

1. Create a Facebook App at [developers.facebook.com](https://developers.facebook.com)
2. App type: **Consumer**
3. Add **Facebook Login** product
4. Set Valid OAuth Redirect URI: `https://{DOMAIN}/auth/callback`
5. For Phase 1, request only `public_profile` and `email` — these do **not** require Meta App Review
6. `user_photos` and `user_friends` require App Review — defer to Phase 2
7. Facebook App starts in **Development Mode**: only people with a role on the app (admin/developer/tester) can log in. Add each family member as a **Tester** in the app dashboard. Limit: 2000 testers. Sufficient for any family.

### 3.2 Environment Variables

```bash
FACEBOOK_APP_ID=123456789
FACEBOOK_APP_SECRET=abc123secret
FACEBOOK_REDIRECT_URI=https://family.martin.fm/auth/callback
SESSION_SECRET=<random 64-char hex string>         # Signs session cookies
ENCRYPTION_KEY=<Fernet.generate_key() output>       # Encrypts Facebook tokens
```

### 3.3 Flow Sequence

```
Browser                    FastAPI                   Facebook                  SQLite
  │                          │                          │                        │
  │  GET /auth/login         │                          │                        │
  │─────────────────────────>│                          │                        │
  │                          │ Generate state token      │                        │
  │                          │ Set oauth_state cookie    │                        │
  │  302 → Facebook OAuth    │                          │                        │
  │<─────────────────────────│                          │                        │
  │                          │                          │                        │
  │  User grants permissions │                          │                        │
  │─────────────────────────────────────────────────────>│                        │
  │                          │                          │                        │
  │  302 → /auth/callback?code=XXX&state=YYY            │                        │
  │─────────────────────────>│                          │                        │
  │                          │                          │                        │
  │                          │  Exchange code for token  │                        │
  │                          │─────────────────────────>│                        │
  │                          │  { access_token, 1-2hr } │                        │
  │                          │<─────────────────────────│                        │
  │                          │                          │                        │
  │                          │  Exchange for long-lived  │                        │
  │                          │─────────────────────────>│                        │
  │                          │  { access_token, 60 day } │                        │
  │                          │<─────────────────────────│                        │
  │                          │                          │                        │
  │                          │  GET /me?fields=...       │                        │
  │                          │─────────────────────────>│                        │
  │                          │  { id, name, email, pic } │                        │
  │                          │<─────────────────────────│                        │
  │                          │                          │                        │
  │                          │  Download profile photo   │                        │
  │                          │─────────────────────────>│                        │
  │                          │  <binary jpg>             │                        │
  │                          │<─────────────────────────│                        │
  │                          │                          │                        │
  │                          │  Upsert person + token    │                        │
  │                          │──────────────────────────────────────────────────>│
  │                          │  Create session            │                        │
  │                          │──────────────────────────────────────────────────>│
  │                          │                          │                        │
  │  302 → /tree             │                          │                        │
  │  Set-Cookie: session=UUID│                          │                        │
  │<─────────────────────────│                          │                        │
```

### 3.4 Token Handling

**Short-lived → Long-lived exchange (immediately after receiving short-lived token):**
```
GET https://graph.facebook.com/v19.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={APP_ID}
  &client_secret={APP_SECRET}
  &fb_exchange_token={SHORT_LIVED_TOKEN}
→ { access_token: "...", token_type: "bearer", expires_in: 5184000 }
```

**Storage:**
- Encrypt long-lived token with `cryptography.fernet.Fernet(settings.encryption_key)`
- Store encrypted blob in `facebook_tokens.access_token_encrypted`
- Store `token_expires_at` (now + `expires_in` seconds)
- Decrypt only when making Graph API calls

**Refresh strategy (Phase 1):**
- No automatic refresh. Long-lived tokens last ~60 days.
- We only fetch profile data once at login. No ongoing API access needed for MVP.
- If a token expires and we need it later, the user simply re-authenticates.

### 3.5 CSRF Protection

- Generate random 32-byte hex string as `state`
- Store in `oauth_state` cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `max_age=600` (10 min)
- On callback: verify `request.query_params["state"] == request.cookies["oauth_state"]`
- Delete `oauth_state` cookie after verification

### 3.6 Person Matching on Callback

On OAuth callback, match the Facebook user to a Person record:

1. **`facebook_id` match** → Found: update token + photo, create session, log in
2. **Email match** (if no `facebook_id` match) → Found: set `facebook_id`, update token + photo, create session
3. **No match** → Create new Person with `manually_added=0`, `is_admin=0`. Admin must later create relationships to position them in the tree.

### 3.7 Scopes Summary

| Scope | Purpose | App Review Required? |
|-------|---------|---------------------|
| `public_profile` | Name, profile picture, Facebook ID | No |
| `email` | Email for matching + contact | No |
| `user_photos` | Photo import (Phase 2) | **Yes** |
| `user_friends` | Auto-discover family (Phase 2) | **Yes** |

### 3.8 Key Implementation Functions (`app/auth.py`)

```python
async def build_login_url(state: str) -> str:
    """Construct Facebook OAuth dialog URL with state param."""

async def exchange_code_for_token(code: str) -> dict:
    """POST to /oauth/access_token. Returns {access_token, token_type, expires_in}."""

async def exchange_for_long_lived_token(short_token: str) -> dict:
    """GET /oauth/access_token with grant_type=fb_exchange_token."""

async def fetch_profile(access_token: str) -> dict:
    """GET /me?fields=id,first_name,last_name,email,picture.width(400).
    Returns {id, first_name, last_name, email, picture: {data: {url}}}."""

async def download_and_store_photo(photo_url: str, person_id: str) -> str:
    """Download Facebook photo URL to /data/photos/{person_id}.jpg.
    Returns relative path for storage in persons.photo_url.
    Facebook CDN URLs expire — must download immediately."""

def encrypt_token(token: str) -> str:
    """Fernet encrypt. Key from settings.encryption_key."""

def decrypt_token(encrypted: str) -> str:
    """Fernet decrypt."""
```

Use `httpx.AsyncClient` for all Facebook API calls.

---

## 4. FastAPI Routes

### 4.1 Auth Router (`/auth`)

| Method | Path | Auth | Purpose | Request | Response |
|--------|------|------|---------|---------|----------|
| `GET` | `/auth/login` | None | Redirect to Facebook OAuth | — | `302 → Facebook` |
| `GET` | `/auth/callback` | None | Handle OAuth callback | `?code=&state=` | `302 → /tree` (set cookie) |
| `POST` | `/auth/logout` | User | Clear session | — | `302 → /` |
| `GET` | `/auth/me` | User | Current user info | — | `PersonSummary` |

**`GET /auth/login` detail:**
- Generate `state = secrets.token_hex(32)`
- Set `oauth_state` cookie (10 min, HttpOnly, Secure, SameSite=Lax)
- 302 redirect to `https://www.facebook.com/v19.0/dialog/oauth?client_id=...&redirect_uri=...&scope=public_profile,email&state=...`

**`GET /auth/callback` detail:**
- Validate `state` matches `oauth_state` cookie → 400 if mismatch
- Exchange `code` for token → exchange for long-lived token
- Fetch profile via Graph API
- Download profile photo to `/data/photos/{person_id}.jpg`
- Upsert person (see matching logic in §3.6)
- Encrypt + store token
- Create session (UUID in `sessions` table, 30-day expiry)
- Set `session` cookie (HttpOnly, Secure, SameSite=Lax, 30 days)
- 302 redirect to `/tree`
- On any error: 302 redirect to `/?error=auth_failed`

**`POST /auth/logout` detail:**
- Mark session as `revoked=1` in DB
- Delete `session` cookie
- 302 redirect to `/`

### 4.2 Persons Router (`/api/persons`)

| Method | Path | Auth | Purpose | Request Body | Response |
|--------|------|------|---------|-------------|----------|
| `GET` | `/api/persons` | User | List all persons | — | `[PersonSummary]` |
| `GET` | `/api/persons/{id}` | User | Get person detail | — | `PersonDetail` |
| `POST` | `/api/persons` | Admin | Create person | `PersonCreate` | `PersonDetail` |
| `PUT` | `/api/persons/{id}` | Admin | Update person | `PersonUpdate` | `PersonDetail` |
| `DELETE` | `/api/persons/{id}` | Admin | Delete person + cascade | — | `204` |
| `POST` | `/api/persons/{id}/photo` | Admin | Upload photo | `multipart/form-data` | `{ photo_url }` |

**Pydantic schemas:**

```python
class PersonSummary(BaseModel):
    """Minimal data for tree rendering and lists."""
    id: str
    first_name: str
    last_name: str
    nickname: str | None
    photo_url: str | None
    country_code: str | None
    branch: str | None
    is_memorial: bool              # computed: death_date is not None

class PersonDetail(PersonSummary):
    """Full person data."""
    patronymic: str | None
    birth_last_name: str | None
    gender: str | None
    birth_date: str | None         # "March 15" format (no year) for non-admins
    death_date: str | None
    location: str | None
    languages: list[str]
    bio: str | None
    contact_whatsapp: str | None
    contact_telegram: str | None
    contact_signal: str | None
    contact_email: str | None
    is_admin: bool
    manually_added: bool
    relationships: list[RelationshipSummary]
    created_at: str
    updated_at: str

class PersonCreate(BaseModel):
    first_name: str                # Required
    last_name: str                 # Required
    nickname: str | None = None
    gender: str | None = None      # "male", "female", or None
    birth_date: str | None = None  # YYYY-MM-DD
    death_date: str | None = None  # YYYY-MM-DD
    location: str | None = None
    country_code: str | None = None  # Validated: 2-letter ISO 3166-1
    languages: list[str] = []
    bio: str | None = None
    branch: str | None = None      # "martin", "semesock", "maternal"
    contact_whatsapp: str | None = None
    contact_telegram: str | None = None
    contact_signal: str | None = None
    contact_email: str | None = None

class PersonUpdate(BaseModel):
    """All fields optional — partial update via PATCH semantics on PUT."""
    first_name: str | None = None
    last_name: str | None = None
    # ... same fields as PersonCreate, all Optional
```

**Photo upload (`POST /api/persons/{id}/photo`):**
- Accepts `multipart/form-data` with a single file field
- Validates: file is JPEG or PNG, size ≤ 10MB
- Saves to `/data/photos/{person_id}.{ext}`
- Updates `persons.photo_url` to relative path
- Returns `{ photo_url: "/photos/{person_id}.jpg" }`

### 4.3 Relationships Router (`/api/relationships`)

| Method | Path | Auth | Purpose | Request Body | Response |
|--------|------|------|---------|-------------|----------|
| `GET` | `/api/relationships` | User | List all | — | `[RelationshipDetail]` |
| `POST` | `/api/relationships` | Admin | Create | `RelationshipCreate` | `RelationshipDetail` |
| `PUT` | `/api/relationships/{id}` | Admin | Update | `RelationshipUpdate` | `RelationshipDetail` |
| `DELETE` | `/api/relationships/{id}` | Admin | Delete | — | `204` |

```python
class RelationshipCreate(BaseModel):
    person_a_id: str               # For parent_child: this is the PARENT
    person_b_id: str               # For parent_child: this is the CHILD
    relationship_type: Literal["parent_child", "spouse", "sibling", "ex_spouse"]
    start_date: str | None = None
    end_date: str | None = None
    status: Literal["active", "dissolved"] = "active"

class RelationshipDetail(BaseModel):
    id: str
    person_a: PersonSummary
    person_b: PersonSummary
    relationship_type: str
    start_date: str | None
    end_date: str | None
    status: str
```

**Validation rules (enforced in handler):**
- `person_a_id != person_b_id` → 400
- Both person IDs must exist → 404
- No duplicate `(person_a_id, person_b_id, relationship_type)` → 409
- For non-directional types (`spouse`, `sibling`, `ex_spouse`): normalize so `person_a_id < person_b_id` lexicographically
- `parent_child` cycle detection: BFS walk from `person_a_id` upward — if `person_b_id` is found as an ancestor, reject → 400 "Would create ancestry cycle"

### 4.4 Tree Router (`/api/tree`)

| Method | Path | Auth | Purpose | Response |
|--------|------|------|---------|----------|
| `GET` | `/api/tree` | User | Full tree data for D3 | `TreeData` |
| `GET` | `/api/tree/relationship/{from_id}/{to_id}` | User | Relationship label between two persons | `{ label, path }` |

**`TreeData` response schema:**

```python
class TreeNode(BaseModel):
    id: str
    first_name: str
    last_name: str
    nickname: str | None
    photo_url: str | None
    country_code: str | None
    branch: str | None
    is_memorial: bool
    gender: str | None

class TreeEdge(BaseModel):
    source: str                   # person ID
    target: str                   # person ID
    relationship_type: str        # parent_child, spouse, sibling, ex_spouse
    status: str                   # active, dissolved

class TreeData(BaseModel):
    nodes: list[TreeNode]
    edges: list[TreeEdge]
    root_id: str | None           # Luna placeholder's ID (center of tree)
    persons: dict[str, PersonDetail]  # Flat map for card rendering without extra API calls
```

The frontend receives flat nodes + edges and converts them into a D3-renderable hierarchy client-side. The `persons` map provides full detail for person cards without additional API calls.

### 4.5 Page Routes (server-rendered HTML via Jinja2)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/` | None | Landing page (`landing.html`) |
| `GET` | `/tree` | User | Tree view (`tree.html`) — redirects to `/` if not authenticated |
| `GET` | `/person/{id}` | User | Person detail (`person.html`) |
| `GET` | `/admin` | Admin | Admin panel (`admin.html`) |

Templates are server-rendered shells. Data is fetched client-side via `fetch()` from `/api/*` endpoints.

### 4.6 Health Router

| Method | Path | Auth | Response |
|--------|------|------|----------|
| `GET` | `/health` | None | `{ status, db, version }` |

```python
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok", "version": "1.0.0"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "db": "unreachable"})
```

---

## 5. Tree Visualization

### 5.1 Library: D3.js v7

**Self-hosted** in `static/js/vendor/d3.v7.min.js` — no CDN, no third-party requests (per spec: "No analytics. No tracking. No third-party scripts.").

**Why D3:**
- Spec says "D3.js or similar"
- Native tree layouts (`d3.tree()` / Reingold-Tilford)
- SVG-based — each node is a DOM element (tappable, accessible)
- Built-in zoom/pan (`d3.zoom()`)
- No framework dependency, no build step
- ~280KB gzipped (single file)

### 5.2 The Spouse Problem

D3's `d3.tree()` expects a strict hierarchy (one parent per node). Family trees aren't trees — spouses create horizontal connections.

**Solution: Couple-node pattern**

1. Build a strict hierarchy from `parent_child` relationships rooted at the root person
2. For each married pair, create a virtual "couple node" at the hierarchy level
3. Both spouses render side-by-side at the couple node's position
4. Children connect to the couple node (which is invisible)
5. Spouse connector drawn as a horizontal line between the two spouse nodes

```
                  [invisible couple node]
                   /                    \
      [Tyler] ═══════════ [Yuliya]       (═══ = spouse connector)
                    |
              [Our Family]
```

### 5.3 Rendering Layers

```
Layer 1: SVG background connection lines (parent→child edges)
Layer 2: Spouse connector lines (horizontal, double-line or dashed for ex_spouse)
Layer 3: Person nodes (circles with photos)
Layer 4: Name labels (text below nodes)
```

### 5.4 Node Rendering

Each person = SVG `<g>` group:

```svg
<g class="person-node" data-id="{id}" data-branch="{branch}" transform="translate(x, y)">
  <!-- Invisible hit area (larger than visible node for easy tapping) -->
  <circle r="40" fill="transparent" class="hit-area" />

  <!-- Photo circle with clip path -->
  <clipPath id="clip-{id}">
    <circle r="30" />
  </clipPath>
  <image href="{photo_url}" width="60" height="60" x="-30" y="-30"
         clip-path="url(#clip-{id})" />

  <!-- Fallback: colored circle + initials (when no photo) -->
  <circle r="30" fill="var(--branch-color)" class="avatar-fallback" />
  <text class="initials" text-anchor="middle" dy="0.35em">TM</text>

  <!-- Memorial ring (dashed border for deceased persons) -->
  <circle r="32" fill="none" stroke="#666" stroke-dasharray="4,4"
          class="memorial-ring" style="display: none" />

  <!-- Name label -->
  <text y="45" text-anchor="middle" class="person-name">{first_name}</text>

  <!-- Country flag emoji -->
  <text y="60" text-anchor="middle" class="person-flag">🇨🇦</text>
</g>
```

### 5.5 Branch Colors

| Branch | Color | CSS Variable | Assignment |
|--------|-------|-------------|------------|
| Martin (paternal) | `#4A90D9` blue | `--branch-martin` | Tyler's ancestors + siblings |
| Semesock (maternal-paternal) | `#6BBF6B` green | `--branch-semesock` | Tyler's mother's family |
| Maternal (Yuliya's family) | `#D94A4A` red | `--branch-maternal` | Yuliya's ancestors + siblings |
| Shared (Luna, future siblings) | `#9B59B6` purple | `--branch-shared` | Direct descendants of Tyler+Yuliya |

Branch is stored on `persons.branch`, set by admin. Untagged persons inherit from closest parent.

### 5.6 Interaction Model

| Interaction | Desktop | Mobile | Result |
|-------------|---------|--------|--------|
| Select person | Click node | Tap node | Open person card overlay |
| Pan | Click + drag background | Touch drag | Move viewport |
| Zoom | Scroll wheel | Pinch | Zoom in/out (0.3x – 3x) |
| Expand/collapse | Click +/- toggle | Tap +/- toggle | Show/hide children subtree |
| Center on person | Double-click | Double-tap | Smooth pan+zoom to center |
| View full profile | Click name label | Tap name label | Navigate to `/person/{id}` |

**D3 zoom config:**
```javascript
const zoom = d3.zoom()
    .scaleExtent([0.3, 3])
    .on("zoom", (event) => {
        svgGroup.attr("transform", event.transform);
    });
svg.call(zoom);
```

**Expand/collapse:** Nodes store `_children` (hidden) vs `children` (visible). Clicking the toggle swaps them and re-renders with 300ms transition (`d3.transition().duration(300)`).

### 5.7 Initial View

- Tree centered on root node
- Two generations visible by default (parents + grandparents)
- Great-grandparents collapsed but expandable
- Auto-fit: compute `initialScale = Math.min(viewportWidth / treeWidth, viewportHeight / treeHeight, 1)` and center
- Animated entry: nodes fade in from center outward over 500ms

### 5.8 Performance

- Max ~200 nodes for a family tree — no virtualization needed
- SVG preferred over Canvas (DOM nodes = accessible, tappable)
- Lazy-load photos: start with colored circle + initials, load `<image>` when node is visible
- Debounce zoom/pan to `requestAnimationFrame`

### 5.9 Tree Construction Flow (client-side)

```
1. fetch('/api/tree') → { nodes, edges, root_id, persons }
2. Build adjacency from edges
3. BFS from root_id following parent_child edges → build hierarchy
4. Identify spouse pairs from spouse edges → create couple nodes
5. d3.hierarchy(root) → d3.tree().nodeSize([100, 160])(hierarchy)
6. Render edges: d3.linkVertical() for parent→child
7. Render spouse connectors: horizontal lines between paired nodes
8. Render nodes: circles + photos + labels
9. Attach zoom + click handlers
10. Auto-fit viewport
```

---

## 6. Person Card Component

### 6.1 Compact Card (Tree Overlay)

Used as a slide-up bottom sheet (mobile) or side panel (tablet+) when tapping a tree node.

```html
<div id="person-card-overlay" class="person-card person-card--compact" hidden
     role="dialog" aria-label="Person details">
  <button class="person-card__close" aria-label="Close">&times;</button>

  <div class="person-card__header">
    <div class="person-card__photo-wrap">
      <img class="person-card__photo" src="" alt="" loading="lazy" />
      <span class="person-card__flag" aria-label="Country"></span>
    </div>
    <div class="person-card__identity">
      <h2 class="person-card__name"></h2>
      <p class="person-card__nickname"></p>
      <p class="person-card__relationship"></p>   <!-- "Uncle", "Бабушка" -->
      <p class="person-card__location"></p>
    </div>
  </div>

  <a class="person-card__detail-link" href="">View full profile →</a>
</div>
```

### 6.2 Full Card (`/person/{id}` page)

```html
<article class="person-card person-card--full">
  <!-- Memorial banner -->
  <div class="person-card__memorial-banner" hidden>In Loving Memory</div>

  <!-- Header -->
  <header class="person-card__header">
    <div class="person-card__photo-wrap person-card__photo-wrap--large">
      <img class="person-card__photo" src="" alt="" />
      <span class="person-card__flag"></span>
    </div>
    <h1 class="person-card__name"></h1>
    <p class="person-card__nickname"></p>
    <p class="person-card__birth-name"></p>         <!-- née / maiden name -->
    <p class="person-card__relationship"></p>
  </header>

  <!-- Bio -->
  <section class="person-card__bio" hidden>
    <p></p>
  </section>

  <!-- Details -->
  <section class="person-card__details">
    <dl class="person-card__detail-list">
      <div class="person-card__detail-item">
        <dt>Birthday</dt>
        <dd class="person-card__birthday"></dd>     <!-- "March 15" — no year -->
      </div>
      <div class="person-card__detail-item">
        <dt>Location</dt>
        <dd class="person-card__location-full"></dd>
      </div>
      <div class="person-card__detail-item">
        <dt>Languages</dt>
        <dd class="person-card__languages"></dd>
      </div>
    </dl>
  </section>

  <!-- Contact buttons -->
  <section class="person-card__contacts" hidden>
    <h2>Contact</h2>
    <div class="person-card__contact-buttons">
      <a class="person-card__contact-btn person-card__contact-btn--whatsapp"
         href="" target="_blank" rel="noopener" hidden>WhatsApp</a>
      <a class="person-card__contact-btn person-card__contact-btn--telegram"
         href="" target="_blank" rel="noopener" hidden>Telegram</a>
      <a class="person-card__contact-btn person-card__contact-btn--signal"
         href="" target="_blank" rel="noopener" hidden>Signal</a>
      <a class="person-card__contact-btn person-card__contact-btn--email"
         href="" hidden>Email</a>
    </div>
  </section>

  <!-- Family connections -->
  <section class="person-card__family">
    <h2>Family</h2>
    <ul class="person-card__family-list">
      <!-- JS populates: <li><a href="/person/{id}"><img /> Tyler (Father)</a></li> -->
    </ul>
  </section>

  <!-- Metadata -->
  <footer class="person-card__meta">
    <p>Last updated: <time datetime=""></time></p>
  </footer>
</article>
```

### 6.3 Data Binding (`person-card.js`)

```javascript
class PersonCard {
    constructor(containerEl) {
        this.el = containerEl;
    }

    render(person) {
        // Photo with fallback
        const img = this.el.querySelector('.person-card__photo');
        img.src = person.photo_url || '/static/img/placeholder.svg';
        img.alt = `${person.first_name} ${person.last_name}`;

        // Name (include nickname if present)
        const nameEl = this.el.querySelector('.person-card__name');
        nameEl.textContent = person.nickname
            ? `${person.first_name} "${person.nickname}" ${person.last_name}`
            : `${person.first_name} ${person.last_name}`;

        // Country flag (ISO alpha-2 → emoji)
        if (person.country_code) {
            this.el.querySelector('.person-card__flag').textContent =
                countryCodeToEmoji(person.country_code);
        }

        // Birthday — "March 15" without year (privacy)
        if (person.birth_date) {
            const d = new Date(person.birth_date + 'T00:00:00');
            this.el.querySelector('.person-card__birthday').textContent =
                d.toLocaleDateString(undefined, { month: 'long', day: 'numeric' });
        }

        // Contact buttons — show only if value exists
        this.bindContact('whatsapp', person.contact_whatsapp,
            (n) => `https://wa.me/${n.replace(/[^0-9]/g, '')}`);
        this.bindContact('telegram', person.contact_telegram,
            (u) => `https://t.me/${u}`);
        this.bindContact('signal', person.contact_signal,
            (n) => `https://signal.me/#p/${n}`);
        this.bindContact('email', person.contact_email,
            (e) => `mailto:${e}`);

        // Memorial state
        if (person.death_date) {
            this.el.classList.add('person-card--memorial');
        }
    }

    bindContact(type, value, hrefFn) {
        const btn = this.el.querySelector(`.person-card__contact-btn--${type}`);
        if (!btn) return;
        if (value) {
            btn.href = hrefFn(value);
            btn.removeAttribute('hidden');
        } else {
            btn.setAttribute('hidden', '');
        }
    }
}

function countryCodeToEmoji(code) {
    return [...code.toUpperCase()]
        .map(c => String.fromCodePoint(0x1F1E6 + c.charCodeAt(0) - 65))
        .join('');
}
```

### 6.4 Admin Controls on Card

If `current_user.is_admin`, the person card shows additional buttons:

- **Edit** → inline form fields replace text (save = `PUT /api/persons/{id}`)
- **Delete** → confirmation dialog → `DELETE /api/persons/{id}`
- **Add Relationship** → dropdown: select existing person + type (parent_child/spouse/sibling) → `POST /api/relationships`
- **Upload Photo** → file picker → `POST /api/persons/{id}/photo`

---

## 7. Mobile-First CSS Strategy

### 7.1 Principles

- **Mobile-first:** All base styles target phones (320px+). Larger screens add via `min-width` queries.
- **Single file** (`static/css/style.css`) — no preprocessor, no build step.
- **CSS custom properties** for theming and branch colors.
- **No framework.** The app has 2 views — vanilla CSS with flexbox is sufficient.
- **System font stack** — handles Latin + Cyrillic + CJK natively. No web fonts to load.

### 7.2 Breakpoints

```css
/* Base: 320px+ (phones) — all core styles written here */

@media (min-width: 768px)  { /* Tablet (landscape iPad) */ }
@media (min-width: 1024px) { /* Desktop */ }
@media (min-width: 1440px) { /* Large desktop — tree gets extra room */ }
```

Only 3 breakpoints. Content-first — if the layout works, don't add a breakpoint.

### 7.3 Viewport Handling

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
```

```css
/* Safe area insets for notched devices (iPhone) */
body {
    padding: env(safe-area-inset-top) env(safe-area-inset-right)
             env(safe-area-inset-bottom) env(safe-area-inset-left);
}

/* Tree container fills viewport minus nav */
.tree-container {
    width: 100%;
    height: calc(100dvh - var(--nav-height));   /* dvh = dynamic viewport height (mobile) */
    overflow: hidden;
    touch-action: none;                          /* D3 handles all touch events */
    overscroll-behavior: none;                   /* Prevent pull-to-refresh on iOS */
}

/* Prevent iOS zoom on input focus */
input, select, textarea {
    font-size: 16px;
}
```

### 7.4 Touch Targets

Per WCAG 2.2 / Apple HIG — minimum 44×44px:

```css
.person-card__contact-btn,
.person-node .hit-area,
button, a {
    min-height: 44px;
    min-width: 44px;
}

.person-card__contact-btn {
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 16px;
}

.person-card__contact-buttons {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
}
```

### 7.5 CSS Custom Properties

```css
:root {
    /* Branch colors */
    --branch-martin: #4A90D9;
    --branch-semesock: #6BBF6B;
    --branch-maternal: #D94A4A;
    --branch-shared: #9B59B6;

    /* UI colors */
    --color-bg: #FAFAFA;
    --color-surface: #FFFFFF;
    --color-text: #1A1A1A;
    --color-text-muted: #666666;
    --color-border: #E0E0E0;
    --color-primary: #4A90D9;

    /* Spacing (4px base) */
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 16px;
    --space-lg: 24px;
    --space-xl: 40px;

    /* Typography */
    --font-family: system-ui, -apple-system, BlinkMacSystemFont,
                   'Segoe UI', Roboto, sans-serif;
    --font-size-sm: 14px;
    --font-size-base: 16px;
    --font-size-lg: 20px;
    --font-size-xl: 28px;
    --line-height: 1.5;

    /* Layout */
    --nav-height: 56px;
    --card-radius: 12px;
    --max-content-width: 640px;
}
```

### 7.6 Person Card Responsive Behavior

```css
/* Mobile: bottom sheet */
.person-card--compact {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    max-height: 50vh;
    border-radius: var(--card-radius) var(--card-radius) 0 0;
    background: var(--color-surface);
    box-shadow: 0 -4px 20px rgba(0,0,0,0.15);
    overflow-y: auto;
    padding: var(--space-lg);
    transform: translateY(100%);
    transition: transform 300ms ease-out;
}
.person-card--compact[data-visible="true"] {
    transform: translateY(0);
}

/* Tablet+: side panel */
@media (min-width: 768px) {
    .person-card--compact {
        position: fixed;
        top: var(--nav-height); right: 0; bottom: 0;
        left: auto;
        width: 360px;
        max-height: none;
        border-radius: 0;
        transform: translateX(100%);
    }
    .person-card--compact[data-visible="true"] {
        transform: translateX(0);
    }
}
```

### 7.7 Layout Strategy Per View

| View | Mobile | Tablet+ |
|------|--------|---------|
| Landing | Single column, centered, max-width 480px | Same, larger type |
| Tree | Full-viewport SVG, floating zoom controls bottom-right, person card as bottom sheet | Full-viewport SVG, person card as right sidebar (360px) |
| Person detail | Single column, max-width 640px, photo full-bleed on mobile | Same, centered |
| Admin | Single column forms, horizontal-scroll tables on mobile | Two-column layout |

---

## 8. Railway Deployment

### 8.1 Dockerfile

```dockerfile
# Stage 1: Build
FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application
COPY . .

# Create persistent data directory
RUN mkdir -p /data/photos

# Non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app /data
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000

# Run migrations then start server (single worker — SQLite doesn't handle concurrent writes)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
```

**Why `--workers 1`:** SQLite cannot handle concurrent writes from multiple processes. Single worker + async I/O handles the load for a family-sized user base (<50 concurrent users).

### 8.2 Environment Variables

| Variable | Required | Example | Purpose |
|----------|----------|---------|---------|
| `FACEBOOK_APP_ID` | Yes | `123456789` | OAuth app ID |
| `FACEBOOK_APP_SECRET` | Yes | `abc123...` | OAuth app secret |
| `FACEBOOK_REDIRECT_URI` | Yes | `https://family.martin.fm/auth/callback` | OAuth callback |
| `SESSION_SECRET` | Yes | (64-char hex) | Session cookie signing |
| `ENCRYPTION_KEY` | Yes | (Fernet key) | Token encryption |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///data/family.db` | Default: `/data/family.db` |
| `ALLOWED_ORIGINS` | No | `https://family.martin.fm` | CORS (comma-separated) |
| `ADMIN_FACEBOOK_IDS` | Yes | `10001234,10005678` | Facebook IDs auto-promoted to admin |
| `ROOT_PERSON_ID` | No | (UUID) | Tree root person. Set after first seed. |
| `DEBUG` | No | `false` | `true` = dev mode (insecure cookies, verbose errors) |
| `PORT` | No | `8000` | Railway sets this automatically |

**Generate secrets:**
```bash
# SESSION_SECRET
python -c "import secrets; print(secrets.token_hex(32))"

# ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 8.3 Railway Volume

**Critical:** SQLite database must live on a persistent volume, not in the app directory (rebuilt on every deploy).

- Mount path: `/data`
- Size: 1 GB (sufficient for family tree + photos)
- Contents: `family.db`, `photos/`

Configure in Railway dashboard → Service → Volumes → Add Volume.

### 8.4 Health Check

Configure in Railway dashboard:
- Path: `/health`
- Interval: 30s
- Start period: 10s (allows for migration run)

### 8.5 Domain Setup

1. Add custom domain in Railway dashboard (e.g., `family.martin.fm`)
2. Create CNAME record → Railway-provided hostname
3. Railway auto-provisions TLS via Let's Encrypt
4. Update `FACEBOOK_REDIRECT_URI` env var
5. Update Facebook App's Valid OAuth Redirect URIs

### 8.6 `pyproject.toml`

```toml
[project]
name = "family-book"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "alembic>=1.13",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "cryptography>=43",             # Fernet encryption for tokens
    "httpx>=0.27",                  # Async HTTP for Facebook API
    "jinja2>=3.1",                  # HTML templates
    "python-multipart>=0.0.9",      # File uploads
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",                  # TestClient
    "ruff>=0.6",
]
```

---

## 9. Gotchas & Edge Cases

### Facebook OAuth

| # | Issue | Impact | Mitigation |
|---|-------|--------|-----------|
| 1 | `user_friends` only returns friends who also use your app | Friends list starts empty for first user | Expected. As more family connects, mutual friends populate. Don't depend on this for Phase 1. |
| 2 | `user_photos` and `user_friends` require Meta App Review | Can't go "Live" without review | Keep app in Development Mode. Add family as Testers (up to 2000). Sufficient for Phase 1. |
| 3 | Facebook profile photo URLs expire (CDN URLs, hours-lived) | Broken images if stored as-is | Download photo on login, save to `/data/photos/{person_id}.jpg`. Never link to `fbcdn.net`. |
| 4 | OAuth `state` race condition (two tabs, one cookie) | Second tab overwrites first tab's state | Accept this. First tab's callback fails → user retries. Not worth solving. |
| 5 | Facebook App Development Mode | Only roles (admin/dev/tester) can log in | Add each family member as Tester before sending them the invite link. |
| 6 | Graph API version deprecation | `v19.0` will eventually be removed | Pin to `v19.0`. Check for deprecation warnings in response headers. Update in ~2 years. |

### SQLite

| # | Issue | Impact | Mitigation |
|---|-------|--------|-----------|
| 7 | WAL mode not enabled by default | Poor read concurrency | Set `PRAGMA journal_mode=WAL` on every connection via event listener. |
| 8 | Foreign keys OFF by default | Cascade deletes don't work | Set `PRAGMA foreign_keys=ON` on every connection. |
| 9 | Railway volume persistence | Data lost if volume not configured | Verify after first deploy: create a person, redeploy, confirm person still exists. |
| 10 | Concurrent writes timeout | Two simultaneous writes → one waits | `PRAGMA busy_timeout=5000` (5s wait). If timeout, return 503. Acceptable for <50 users. |
| 11 | Database file corruption on crash | Data loss | WAL mode is crash-safe. Additionally: nightly backup (Phase 2, cron to R2). |

### Tree Visualization

| # | Issue | Impact | Mitigation |
|---|-------|--------|-----------|
| 12 | Spouses don't fit D3's tree hierarchy | Layout breaks | Couple-node pattern (§5.2). Virtual invisible node, spouses rendered side-by-side. |
| 13 | Disconnected persons (no relationships yet) | Orphan nodes float | Show disconnected persons in a separate "Unconnected" section below the tree. Admin CTA: "Connect this person." |
| 14 | Single-parent branches | Missing parent position | D3 handles single-child hierarchies. If only one parent exists, that parent is the only node at that level. No phantom second parent. |
| 15 | Wide generation (6+ siblings) | Overflows mobile viewport | Initial auto-fit zoom handles this. Pan/zoom to navigate. |
| 16 | SVG `<image>` photo loading | 50+ images = jank | Lazy-load: start with circle + initials, replace with photo when node enters viewport (IntersectionObserver or distance check). |
| 17 | Mobile Safari SVG tap events | Click events sometimes ignored on SVG `<g>` | Set `pointer-events: all` on SVG groups. |

### Person Data

| # | Issue | Impact | Mitigation |
|---|-------|--------|-----------|
| 18 | Child's name must never appear in UI | Privacy violation | Root person's `first_name` = "Our", `last_name` = "Family" in DB. API response always returns "Our Family" for root. |
| 19 | Country code → flag emoji | May not render on some systems | Works on iOS, Android, Win 10+, macOS. Fallback: display 2-letter code. |
| 20 | Birth year privacy | Revealing age | Display as "March 15" (no year) for non-admin users. Admin sees full date. |
| 21 | Duplicate person on OAuth | Same person exists manually + logs in via Facebook | Match by: (1) `facebook_id`, (2) email, (3) flag name match for admin review. Never auto-merge on name alone — recycled names in families. |
| 22 | Gender for relationship labels | "Father" vs "Mother" requires gender | `gender` column, nullable. Default to gender-neutral ("Parent", "Grandparent", "Sibling") if NULL. |

### Deployment

| # | Issue | Impact | Mitigation |
|---|-------|--------|-----------|
| 23 | First deploy — empty database | Empty tree view | Show empty state: "No family members yet. Add your first." + seed script option. |
| 24 | CORS in development | Frontend on :5173, backend on :8000 | `ALLOWED_ORIGINS` env var. In dev, set to `http://localhost:5173`. |
| 25 | `Secure` cookies on localhost | Cookies rejected over HTTP | `DEBUG=true` → set `secure=False` on cookies. |
| 26 | Photo storage without R2 | Disk storage won't scale | Phase 1: store in `/data/photos/` on Railway volume. Move to R2/S3 in Phase 2. |
| 27 | Railway cold starts (free tier) | 5-10s first request after sleep | Use Pro plan ($5/mo) for always-on. Or accept cold starts for MVP. |
| 28 | Alembic migrations on startup | Failed migration blocks deploy | CMD runs `alembic upgrade head` before uvicorn. If migration fails, container exits, Railway retries (up to 3). Check Alembic migration is idempotent. |

### Seed Data

**`seed.json` format** — human-friendly, names instead of UUIDs:

```json
{
  "persons": [
    {
      "ref": "root",
      "first_name": "Our",
      "last_name": "Family",
      "branch": "shared",
      "_note": "Root node — never displays real child name"
    },
    {
      "ref": "tyler",
      "first_name": "Tyler",
      "last_name": "Martin",
      "gender": "male",
      "location": "Madrid, Spain",
      "country_code": "ES",
      "languages": ["en"],
      "is_admin": true,
      "branch": "martin"
    },
    {
      "ref": "yuliya",
      "first_name": "Yuliya",
      "last_name": "...",
      "gender": "female",
      "country_code": "ES",
      "is_admin": true,
      "branch": "maternal"
    }
  ],
  "relationships": [
    { "parent": "tyler", "child": "root", "type": "parent_child" },
    { "parent": "yuliya", "child": "root", "type": "parent_child" },
    { "a": "tyler", "b": "yuliya", "type": "spouse" }
  ]
}
```

The `ref` field is a human-friendly key used only for cross-referencing within the seed file. The seed script generates UUIDs and resolves refs to UUIDs during import. The script is idempotent — re-running it upserts by `ref` (stored in a `_seed_ref` column or matched by name).

---

## 10. Implementation Order

Execute in this sequence. Each step is independently testable.

1. **Repo scaffolding** — `pyproject.toml`, `.gitignore`, `.env.example`, directory structure, CLAUDE.md
2. **Database** — `app/database.py`, `app/models.py`, Alembic migration (`001_initial_schema.py`), WAL mode, FK enforcement
3. **Config** — `app/config.py` with pydantic-settings, all env vars
4. **Seed script** — `app/seed.py` + `seed.json` with Tyler/Yuliya family skeleton. Run, verify data in SQLite.
5. **Health endpoint** — `GET /health` with DB check. Deploy skeleton to Railway, verify health.
6. **People CRUD** — `app/routers/persons.py`, `app/schemas.py`. Test with curl/httpx.
7. **Relationships CRUD** — `app/routers/relationships.py`, validation (cycles, duplicates). Tests.
8. **Graph engine** — `app/graph.py`: BFS, relationship labeling. Comprehensive unit tests.
9. **Tree API** — `GET /api/tree` returning D3-compatible data. Test with seed data.
10. **Facebook OAuth** — `app/auth.py`, `app/routers/auth.py`, session middleware, photo download. Test against Facebook sandbox.
11. **Landing page** — `templates/landing.html`, CSS. "Connect with Facebook" button.
12. **Tree visualization** — `templates/tree.html`, `static/js/tree.js`, D3 rendering, zoom/pan, couple nodes.
13. **Person card** — `static/js/person-card.js`, bottom sheet / sidebar, data binding.
14. **Admin controls** — Inline edit/delete on person cards, relationship creation. `templates/admin.html`.
15. **Railway production deploy** — Dockerfile, volume, env vars, custom domain, Facebook redirect URI.
16. **End-to-end test** — Full flow: landing → Facebook login → tree → tap person → card → admin edit.
