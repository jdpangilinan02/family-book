# Family Book — Spec v1

**A private, self-hosted family tree and archive with graph-distance privacy.**

"Facebook is the mall. This is our living room."

---

## Vision

A private website where Tyler's daughter Luna can see all her family — faces, names, relationships, locations — across Canada, Russia, and Spain. Family members connect via Facebook OAuth, their data gets imported automatically, and the family tree computes privacy permissions based on relationship distance. No ads. No algorithms. No Zuckerberg.

## Core Concepts

### The Family Graph
Every person is a node. Edges are relationships (parent, child, spouse, sibling). The graph computes:
- Relationship labels ("2nd cousin once removed", "тётя", "uncle")
- Permission layers (see below)
- Ancestry paths ("Luna → Yuliya → Бабушка Наташа → ...")

### Graph-Distance Privacy
Permissions are computed, not configured. The tree IS the ACL.

| Layer | Who | Can See |
|-------|-----|---------|
| 0 | Luna (root) | Everything |
| 1 | Parents (Tyler, Yuliya) | Full admin + all data |
| 2 | Grandparents, siblings of parents | Their branch + shared ancestors, contact info |
| 3 | Aunts/uncles, first cousins | Their branch, shared connections, photos |
| 4 | Second cousins | Names, photos, location, country |
| 5 | Third+ cousins, distant | Name, country, flag. Existence only. |

### Life-Event Mutations
- **Marriage:** Spouse grafted to partner's layer minus one depth
- **Divorce:** Ex drops to Layer 5. Children retain natural layer.
- **Death:** Profile becomes memorial. Photos preserved. Contact info removed.
- **Estrangement:** Admin override to Layer 5 or hidden.
- **New baby:** Inherits closer parent's layer.

## User Journey

### For family members (Aunt Shelley, Cousin Dmitri, etc.)
1. Receive WhatsApp/Messenger message from Tyler with link
2. Tap link → beautiful landing page explaining "Family Book"
3. Tap "Connect with Facebook" → standard OAuth
4. Grant permissions (public profile, email, friends list, photos)
5. See confirmation: "Welcome! Your photos are being imported."
6. Facebook data export prompt: "For a complete backup, tap here to request your Facebook data export. When you get the email from Facebook, just forward it to family@martin.fm"
7. Done. ~2 minutes. Maybe 3 if they read slowly.

### For Luna (the primary audience)
- Opens site on iPad
- Sees a visual family tree — faces in circles, lines connecting them
- Taps a face → sees their card: photo, name, relationship, location, flag, birthday
- Can browse by country ("Who lives in Canada?"), by relationship ("My cousins"), or by the full tree
- World map with pins
- Birthday calendar ("Дядя Саша's birthday is in 3 days!")

### For Tyler/Yuliya (admins)
- Full CRUD on family tree structure
- Override privacy layers when needed
- See import status for each family member
- Approve/reject suggested connections from Facebook data
- Add people manually who aren't on Facebook (great-grandparents, deceased relatives)

## Technical Architecture

### Stack
- **Frontend:** Static site (vanilla HTML/CSS/JS or lightweight framework). Mobile-first.
- **Backend:** Python FastAPI (lightweight). Handles OAuth, data import, tree computation.
- **Database:** SQLite (simple) or PostgreSQL (if we want Mastodon later).
- **Hosting:** Railway or Cloudflare Pages + Workers.
- **Domain:** TBD (martin.fm, semesock.com, or new)
- **Email ingestion:** Envelope (already built) for Facebook data export forwarding.

### Data Model

```
Person {
  id: uuid
  first_name: str
  last_name: str
  nickname: str (optional)
  photo_url: str
  birth_date: date (optional)
  death_date: date (optional, makes it a memorial)
  location: str (city, country)
  country_code: str (for flags)
  languages: [str]
  bio: str (optional, short)
  contacts: {
    whatsapp: str (phone number)
    telegram: str (username)
    signal: str (phone number)
    email: str
  }
  facebook_id: str (from OAuth)
  is_admin: bool
  manually_added: bool
  created_at: datetime
  updated_at: datetime
}

Relationship {
  person_a: uuid
  person_b: uuid
  type: enum (parent_child, spouse, sibling, ex_spouse)
  start_date: date (optional — marriage date, birth date)
  end_date: date (optional — divorce date, death date)
  status: enum (active, dissolved)
}

ImportedAsset {
  id: uuid
  person_id: uuid
  source: enum (facebook_oauth, facebook_export, whatsapp, manual)
  asset_type: enum (photo, post, profile_info, friends_list)
  data: json
  imported_at: datetime
}
```

### Facebook OAuth Flow
1. Register Facebook App (Facebook Developer Console)
2. Request permissions: `public_profile`, `email`, `user_photos`, `user_friends`
3. OAuth callback → store token, fetch basic profile + profile photo
4. `user_friends` only returns friends who ALSO use your app — perfect for family, incentivizes inviting each other
5. Store Facebook ID for deduplication

### Facebook Data Export Ingestion
1. Family member requests data export from Facebook Settings
2. Facebook emails them a download link (24-48h later)
3. They forward the email to `family@martin.fm`
4. Envelope receives email → Skippy/pipeline extracts download URL
5. Download .zip → parse JSON files:
   - `profile_information/profile_information.json` → name, birthday, location, relationship status
   - `friends_and_followers/friends.json` → friend list (for graph building)
   - `photos_and_videos/album/` → all photos with timestamps
   - `about_you/family_members.json` → **actual family relationship data from Facebook**
6. Match to existing Person nodes or create new ones
7. Photos stored in private bucket (R2/S3), referenced by URL

### WhatsApp Profile Sync
- Weekly cron via `wacli`
- Pull profile photos for all family contacts
- Update `photo_url` if changed
- Pull status text as a "latest update"
- Zero effort from family members

### Graph Computation
- BFS from any person to compute relationship distance
- Relationship labeling algorithm:
  - Find common ancestor(s)
  - Count generations up from person A to ancestor
  - Count generations down from ancestor to person B
  - Compute: parent, grandparent, uncle/aunt, cousin, nth cousin m-times removed
- Cache computed relationships (invalidate on tree changes)
- Support both English and Russian relationship terms (Russian has specific words for maternal vs paternal grandparents, etc.)

### Federation: Family Book ↔ Family Book (Phase 2)
Each domain runs its own Family Book with its own SQLite. Families connect across domains via APIs.

**Architecture:**
- `martin.fm` has the Martin/Semesock family SQLite
- `garcia.family` has the Garcia family SQLite
- When a Martin marries a Garcia, the two instances exchange minimal graph data via API
- Each instance retains sovereignty — your data stays on your domain
- Shared nodes (the couple) exist in both databases with a federation link
- Permission layers cross federation boundaries: a Garcia cousin sees Martin family at Layer 4+ only

**Federation API:**
```
POST /api/v1/federation/invite   — propose a cross-family link
POST /api/v1/federation/accept   — accept and exchange graph stubs
GET  /api/v1/federation/person/{id}  — fetch a person card (respects permission layer)
```

- No central registry. Families discover each other through marriage/relationship links.
- Each instance is a sovereign SQLite. No shared database. No vendor lock-in.
- The protocol is simple enough that any developer can stand up a Family Book instance.

### Mastodon/ActivityPub (Phase 3, optional)
- GoToSocial instance on `social.martin.fm` (lightweight, single-purpose)
- Each family member gets a fediverse handle
- Family updates post to the instance
- Federated — anyone with Mastodon can follow
- But the instance is invite-only (admin = Tyler)

## Privacy & Security

- **No child's name on the site.** The root of the tree is labeled "Our Family" or "The Family" in the UI. The child's real name never appears in any public-facing or shared content. Internal data model uses a generic identifier.
- **No analytics. No tracking. No third-party scripts.**
- **All data stored on Tyler's infrastructure** (Railway/R2)
- **Facebook tokens stored encrypted at rest**
- **Photos served from private bucket with signed URLs** (no public CDN)
- **Admin-only data deletion** — Tyler can purge any person's data completely
- **GDPR compliant by design** — each person can request their data export or deletion
- **Client-side passphrase option** for extra paranoid family members

## UI/UX

### Landing page (public)
- "Family Book — A private place for our family"
- "Connect with Facebook" button (big, obvious)
- Brief explanation (3 sentences max)
- Tyler and Yuliya's faces as trust anchors

### Tree view (authenticated)
- Interactive tree visualization (D3.js or similar)
- Horizontal scrolling for wide trees
- Tap to expand/collapse branches
- Color-coded by family branch (Martin = blue, Semesock = green, Yuliya's family = red)

### Person card (authenticated)
- Photo (circle crop)
- Name + nickname
- Relationship to Luna (computed)
- Location + flag
- Birthday (if within permission layer)
- Contact buttons (WhatsApp, Telegram, Signal — if within permission layer)
- Photo gallery (if imported)
- "Last updated" timestamp

### World map
- Pins for each family member
- Color-coded by branch
- Tap pin → person card
- "5 family members in Canada, 8 in Russia, 3 in Spain"

### Birthday calendar
- Monthly view
- Upcoming birthdays highlighted
- Auto-generated "Happy Birthday!" reminders via WhatsApp (optional)

## Phase Plan

### Phase 1 — MVP (1-2 weeks)
- [ ] Repo setup, CLAUDE.md
- [ ] Data model + SQLite
- [ ] Facebook OAuth flow
- [ ] Manual family tree entry (admin UI or JSON seed)
- [ ] Basic tree visualization
- [ ] Person cards
- [ ] Mobile-first responsive design
- [ ] Deploy to Railway + domain

### Phase 2 — Import Pipeline (1 week)
- [ ] Facebook data export email ingestion via Envelope
- [ ] Export parser (photos, profile, friends, family)
- [ ] WhatsApp profile photo sync via wacli
- [ ] Photo storage (R2 or S3)

### Phase 3 — Privacy Engine (1 week)
- [ ] Graph-distance computation
- [ ] Permission layer enforcement
- [ ] Life-event mutations (marriage, divorce, death)
- [ ] Admin override UI

### Phase 4 — Polish (1 week)
- [ ] World map
- [ ] Birthday calendar
- [ ] Russian/Spanish/English i18n
- [ ] Russian relationship terms (дядя, тётя, бабушка, дедушка, etc.)
- [ ] PWA for tablet (Luna's iPad)

### Phase 5 — Federation (optional)
- [ ] GoToSocial instance
- [ ] ActivityPub integration
- [ ] Family member fediverse handles

## Human-Only Bottlenecks
1. Initial family tree structure (Tyler + Yuliya, one evening)
2. Phone numbers for WhatsApp sync (contact export)
3. Facebook Developer App registration (~30 min)
4. Domain choice
5. Sending the invitation messages to family

## Internationalization (i18n)

### Design Principle
Any language on the fly. No hardcoded translation files for every locale. Use LLM-powered translation via OpenRouter API at runtime with aggressive caching.

### How It Works
1. **Base language:** English (all UI strings stored as English keys)
2. **User selects language** from any language in the world (dropdown or browser `Accept-Language`)
3. **First load in new locale:** OpenRouter API call translates all UI strings + relationship labels in batch
4. **Cache translations** in SQLite `translations` table (locale + key → translated string)
5. **Subsequent loads:** served from cache, zero API calls
6. **Relationship terms** are locale-aware:
   - Russian: бабушка по маме vs бабушка по папе, дядя, тётя, двоюродный брат
   - Spanish: abuela materna vs abuela paterna, tío, tía, primo segundo
   - English: maternal grandmother, uncle, second cousin once removed
   - Any other language: computed via OpenRouter on first request, cached forever
7. **Patronymics** (Russian naming): data model supports `patronymic` field, displayed when locale = ru
8. **Maiden names**: stored as `birth_last_name`, displayed contextually
9. **RTL support**: CSS logical properties (margin-inline-start, etc.) for Arabic, Hebrew, Farsi

### Translation Storage
- **JSON files, NOT SQLite.** Translations are static assets, not relational data.
- One file per locale: `locales/en.json`, `locales/ru.json`, `locales/es.json`, etc.
- Generated on first request via OpenRouter, saved to disk, served statically
- Frontend loads the JSON directly — no API call needed after first generation
- Git-committable: translations become part of the repo, auditable, editable by humans
- Format:
```json
{
  "_meta": { "locale": "ru", "generated": "2026-03-15", "source": "openrouter" },
  "ui": { "birthday_calendar": "Календарь дней рождения", ... },
  "rel": { "second_cousin_once_removed": "троюродный брат/сестра", ... }
}
```

### Translation API
- Provider: OpenRouter (`https://openrouter.ai/api/v1/chat/completions`)
- Model: cheapest capable model (e.g., `google/gemini-2.0-flash` or similar)
- Prompt: structured batch translation with relationship-term glossary for accuracy
- Cost: ~$0.001 per language bootstrap (one-time per locale)
- Fallback: English if API unavailable
- Output: written to `locales/{locale}.json`, then served as static file

### Data Model Addition (SQLite — family data only)
```
Person (additional fields) {
  patronymic: str (optional — Russian/Arabic naming)
  birth_last_name: str (optional — maiden name)
  name_display_order: enum (western, eastern, patronymic) — default: western
}
```

## Non-Goals
- This is NOT a social network replacement
- This is NOT a genealogy research tool (no Ancestry.com integration)
- This is NOT public-facing
- No user-generated content moderation needed (it's family)
- No monetization. Ever.

## Name
**Family Book** / **Libro de Familia** / **Семейная Книга**
