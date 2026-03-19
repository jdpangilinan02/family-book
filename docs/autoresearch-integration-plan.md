# 20260319 Family Book + autoresearch-genealogy Integration Plan

**Date:** 2026-03-19
**Status:** Draft
**Repo:** [mattprusak/autoresearch-genealogy](https://github.com/mattprusak/autoresearch-genealogy)

---

## Executive Summary

autoresearch-genealogy is a structured prompt system for AI-assisted genealogy research built for Claude Code. It provides 12 autonomous research prompts, Obsidian vault templates, 24 country/region archive guides, and methodology docs (confidence tiers, source hierarchy, naming conventions). Family Book already has the data model foundations needed for integration: source tracking on every fact, fuzzy dates, patronymic naming, and confidence levels on relationships. The integration makes Family Book the authoritative data store while autoresearch becomes the research engine that fills gaps.

**Core principle:** Data stays sovereign. autoresearch reads from and writes proposals back to Family Book. The family graph never leaves the system. Research findings are staged for human review before becoming facts.

---

## 1. Data Model Mapping: autoresearch vault <-> Family Book

### Person File Frontmatter -> Person Model

| autoresearch field | Family Book field | Notes |
|---|---|---|
| `name` | `first_name` + `last_name` + `patronymic` | FB splits names; autoresearch uses full name string. Exporter must parse/join. |
| `born` | `birth_date` + `birth_date_raw` + `birth_date_precision` | FB supports fuzzy dates natively ("~1960", "before 1945"). Map `birth_date_raw` to vault, normalize to ISO for `born`. |
| `died` | `death_date` + `death_date_raw` + `death_date_precision` | Same fuzzy date handling. |
| `family` | `last_name` / `birth_last_name` | autoresearch uses surname grouping. Map to `birth_last_name` for married women. |
| `confidence` | Maps to relationship `confidence` enum | autoresearch: high/moderate/low/stub. FB: confirmed/probable/uncertain/unknown. See mapping below. |
| `sources` | `source` enum + `source_detail` | FB has enum for provenance type + free-text detail. autoresearch has freeform source list. |
| `tags` | No direct equivalent | Tags are vault-internal. Not imported. |
| (body: Father, Mother) | `ParentChild` records | autoresearch lists parents inline; FB uses relationship table with `kind` and `confidence`. |
| (body: Spouse) | `Partnership` records | autoresearch lists spouse inline; FB uses Partnership with `kind`, `status`, `start_date`. |
| (body: Children) | `ParentChild` records (inverse) | |
| (body: Birthplace) | `birth_place` + `birth_country_code` | autoresearch uses free text; FB splits place + ISO country code. |
| (body: Burial) | `burial_place` | Direct map. |
| (body: Biography) | `bio` | FB caps at 2000 chars. Longer bios truncate with link to full research note. |
| (body: Document Sources table) | Multiple `source_detail` entries + proposed ResearchNote model | See Section 5. |
| (body: Data Discrepancies table) | No direct equivalent | Proposed: store as ResearchNote with `kind=discrepancy`. |

### Confidence Tier Mapping

| autoresearch | Family Book | Evidence Requirement |
|---|---|---|
| high (Strong Signal) | `confirmed` | 2+ independent sources, primary documents, no contradictions |
| moderate (Moderate Signal) | `probable` | 1 primary source OR multiple agreeing secondary sources |
| low (Speculative) | `uncertain` | Single tertiary source, circumstantial, or contradictory evidence |
| stub | `unknown` | No sourcing at all |

### Source Hierarchy Mapping

| autoresearch Tier | Family Book `source` enum | Examples |
|---|---|---|
| Tier 1 (Primary) | `manual` with `source_detail` citing record | Vital records, church registers, military records, immigration manifests |
| Tier 2 (Secondary) | `manual` with `source_detail` | Obituaries, published genealogies, compiled indexes |
| Tier 3 (Tertiary) | `manual` with `source_detail` + lower confidence | User-contributed trees, oral history, forum posts |
| AI-discovered | Proposed: `ai_research` enum value | Findings from autoresearch sessions, always staged for review |

**Schema change needed:** Add `ai_research` to the `source` enum on Person, ParentChild, and Partnership models.

---

## 2. Import/Export Flow: Family Book <-> Vault Format

### Export: Family Book -> autoresearch vault (Markdown + YAML)

Generate a temporary vault directory that autoresearch prompts can operate on:

```
/data/research/vault/
  Family_Tree.md          # Generated from FB graph
  Research_Log.md         # Empty or seeded from prior sessions
  Open_Questions.md       # Generated from FB gaps
  Data_Inventory.md       # Generated from FB source counts
  Timeline.md             # Generated from FB dates
  people/
    John_Smith_1890.md    # One file per Person, vault-template/templates/person.md format
    ...
```

**Export logic (`app/services/research_export.py`):**

1. Query all Person records (or scoped to a subtree)
2. For each Person, render `person.md` template:
   - YAML frontmatter: `type`, `name` (joined), `born`, `died`, `family`, `confidence` (mapped), `sources` (from source_detail), `created`
   - Body: vital info table, biography, document sources, discrepancies
3. Generate `Family_Tree.md` from ParentChild + Partnership graph
4. Generate `Open_Questions.md` from persons with `confidence=uncertain/unknown` or missing key dates
5. Generate `Timeline.md` from all dated events
6. Write to `/data/research/vault/{session_id}/`

**Format:** Standard markdown with YAML frontmatter, matching autoresearch vault-template exactly. No proprietary formats.

### Import: autoresearch vault -> Family Book (Research Findings)

After a research session produces changes to vault files:

1. **Diff detection:** Compare post-research vault against pre-research snapshot
2. **Parse changes:** Extract new persons, updated fields, new sources, new relationships
3. **Stage as proposals:** Create `ResearchProposal` records (new model) with:
   - `kind`: new_person, update_field, new_relationship, new_source, discrepancy
   - `target_person_id`: existing Person UUID (null for new persons)
   - `field`: which field changed
   - `proposed_value`: the new value
   - `source_citation`: what autoresearch found
   - `confidence`: mapped from autoresearch tier
   - `session_id`: links to the research session
   - `status`: pending, accepted, rejected
4. **Admin review UI:** HTMX-rendered review queue (see Section 4)
5. **Accept/reject:** Admin reviews each proposal. Accepted proposals create/update records with `source=ai_research` and full `source_detail`.

**Key constraint:** Nothing from autoresearch modifies Family Book data without human approval. This is non-negotiable for data sovereignty.

### New Models Required

```python
class ResearchSession(Base):
    id: UUID
    name: str                    # "Tree expansion - Rivera line"
    prompt_used: str             # "01-tree-expansion"
    scope_person_id: UUID | None # If scoped to a subtree
    vault_path: str              # /data/research/vault/{session_id}/
    status: enum                 # preparing, running, completed, reviewing, closed
    stats: JSON                  # { persons_added: N, sources_found: N, ... }
    started_at: datetime
    completed_at: datetime | None
    created_by: UUID

class ResearchProposal(Base):
    id: UUID
    session_id: UUID             # FK -> ResearchSession
    kind: enum                   # new_person, update_field, new_relationship, new_source, discrepancy
    target_person_id: UUID | None
    field: str | None
    current_value: str | None
    proposed_value: str
    source_citation: str         # The evidence autoresearch found
    confidence: enum             # confirmed, probable, uncertain, unknown
    status: enum                 # pending, accepted, rejected, deferred
    reviewer_id: UUID | None
    reviewer_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
```

---

## 3. Prompt Priority: Which to Integrate First

Ranked by value to Family Book, accounting for existing data model support and Alex's family spanning the US, Japan, Spain, and Brazil.

### Tier 1 - Integrate immediately (high value, direct model support)

| # | Prompt | Why | FB Support |
|---|---|---|---|
| 01 | **Tree Expansion** | Core value prop: fill gaps in the family tree. Every leaf node is a research target. | Person, ParentChild, Partnership models ready. Fuzzy dates and patronymics built. |
| 05 | **Source Citation Audit** | FB already tracks sources on every entity. This prompt audits completeness and upgrades confidence. | `source`, `source_detail`, `confidence` fields exist. |
| 06 | **Unresolved Persons** | Identifies witnesses, sponsors, recurring names in imported media/moments that aren't yet linked. | WhatsApp/Messenger imports create Moments with captions containing unlinked names. |
| 07 | **Timeline Gap Analysis** | Identifies missing records (census, vital, military) for each person. Directly maps to FB's fuzzy date precision fields. | `birth_date_precision`, `death_date_precision` signal where gaps exist. |

### Tier 2 - Integrate after Tier 1 (high value, needs GEDCOM or additional work)

| # | Prompt | Why | Prereq |
|---|---|---|---|
| 02 | **Cross-Reference Audit** | Resolves conflicts between sources. Needs enough data in the system first. | Tier 1 populates data; then audit for consistency. |
| 04 | **GEDCOM Completeness** | FB has GEDCOM import on the roadmap. This validates export quality. | GEDCOM import/export must be built first. |
| 08 | **Open Question Resolution** | Structured research on specific unknowns. Needs the Open_Questions tracking system. | ResearchSession model + question tracking UI. |
| 11 | **Immigration Search** | High value for Alex's family (cross-border immigration). | Country-specific archive guides integrated. |

### Tier 3 - Integrate later (specialized)

| # | Prompt | Why | Notes |
|---|---|---|---|
| 03 | **FindAGrave Sweep** | Valuable for deceased ancestors. Lower urgency than living tree expansion. | Straightforward web search prompt. |
| 09 | **Bygdebok Extraction** | Scandinavian-specific. Not relevant to Alex's family lines. | Skip unless family lines expand. |
| 10 | **Colonial Records Search** | US colonial focus. Marginal relevance unless Rivera line goes back far enough. | Defer. |
| 12 | **DNA Chromosome Analysis** | Requires 23andMe/AncestryDNA CSV exports. Separate data pipeline. | See Section 7. |

---

## 4. UI Integration: Triggering Research from Family Book

### "Research This Person" Button

On every Person profile page, add a research action dropdown (admin only):

```html
<!-- In person detail template, admin actions section -->
<div hx-get="/admin/research/start?person_id={{person.id}}"
     hx-target="#research-modal" hx-trigger="click">
  Research This Person
</div>
```

**Flow:**

1. Admin clicks "Research This Person" on any profile
2. Modal opens with prompt selection:
   - "Expand ancestors" (prompt 01)
   - "Audit sources" (prompt 05)
   - "Find missing records" (prompt 07)
   - "Search immigration records" (prompt 11)
   - "Find grave memorial" (prompt 03)
3. Admin optionally scopes research (this person only, this person + ancestors, entire branch)
4. System exports scoped vault, runs selected prompt
5. Admin is notified when research completes
6. Admin reviews proposals in `/admin/research/{session_id}/review`

### Research Dashboard (`/admin/research`)

| Section | Content |
|---|---|
| Active sessions | Running research sessions with progress |
| Review queue | Proposals awaiting admin decision, grouped by session |
| History | Past sessions with accept/reject stats |
| Gap analysis | Auto-generated list of persons with lowest confidence or fewest sources |

### Review Queue UI

Each proposal rendered as an HTMX card:

```
[Person: Иван Семесок (b. ~1920)]
[Field: birth_place]
[Current: (unknown)]
[Proposed: Минск, Беларусь]
[Source: "FamilySearch record K39-281, baptismal register 1920"]
[Confidence: probable]
[Accept] [Reject] [Defer] [Edit & Accept]
```

"Edit & Accept" allows admin to modify the proposed value before accepting (e.g., fix transliteration, add detail).

### Research Status Indicators on Tree

On the D3 tree visualization, nodes could show research status:
- Green ring: all key fields sourced (confidence >= probable)
- Yellow ring: has gaps (missing dates, single source)
- Red ring: stub (no sources, minimal data)
- Pulse animation: active research session targeting this person

---

## 5. Research Findings Flow: autoresearch -> Family Book

### The Pipeline

```
[autoresearch session runs on vault copy]
        |
        v
[Diff engine detects changes]
        |
        v
[Parser extracts structured proposals]
        |
        v
[ResearchProposal records created in DB]
        |
        v
[Admin notification: "12 findings ready for review"]
        |
        v
[Admin reviews in /admin/research/{id}/review]
        |
        v
[Accepted proposals applied to Person/ParentChild/Partnership]
        |
        v
[AuditLog entries created with source=ai_research]
```

### Proposal Types and Their Effects

| Proposal Kind | On Accept |
|---|---|
| `new_person` | Creates Person record with all proposed fields. Sets `source=ai_research`, `source_detail` = citation. |
| `update_field` | Updates the specified field on existing Person. Old value preserved in AuditLog. |
| `new_relationship` | Creates ParentChild or Partnership record with proposed confidence and source. |
| `new_source` | Adds/upgrades `source_detail` on existing record. May upgrade `confidence` if evidence warrants. |
| `discrepancy` | Creates a note flagging conflicting information. Does not auto-resolve; admin decides. |

### Source Citation Storage

autoresearch produces detailed citations like:
> "FamilySearch film 2114459, item 3, Minsk guberniya metric books, 1918-1922, entry 47"

These map to:
- `source` = `ai_research` (how it entered the system)
- `source_detail` = the full citation string (what the evidence is)
- A future `ResearchNote` model could store the full narrative context, discrepancy analysis, and search log

### Confidence Upgrade Rules

When a research finding upgrades an existing record's confidence:
- `unknown` -> `uncertain`: Any source found at all
- `uncertain` -> `probable`: Primary source found, or 2+ secondary sources agree
- `probable` -> `confirmed`: 2+ independent primary sources agree, no contradictions

Confidence can only be upgraded through the review queue. It never auto-downgrades.

---

## 6. Country-Specific Guide Integration

Alex's family spans four key regions. autoresearch provides archive guides for all of them.

### Relevant Archive Guides

| Region | autoresearch Guide | Key Resources | Language Challenges |
|---|---|---|---|
| **Canada** | `archives/canada.md` | LAC (census 1825-1921, immigration 1865-1935), PRDH (Quebec parish registers 1621-1799), AutomatedGenealogy.com, Canadiana | English/French bilingual records |
| **Russia** | `archives/russia-ukraine.md` | FamilySearch (metric books by guberniya), JewishGen, VGD.ru, Pamyat Naroda (WWII), OBD Memorial | Cyrillic, pre-1918 Julian calendar, patronymics, name transliteration |
| **Spain** | `archives/spain-portugal.md` | PARES (Archivo General de Indias, Archivo Historico Nacional), FamilySearch Spain, regional archives (Catalonia, Basque, Galicia, Andalusia) | Spanish, Catholic parish records from 1500s |
| **Puerto Rico** | `archives/mexico-latin-america.md` + `archives/spain-portugal.md` | FamilySearch (Catholic parish records), Puerto Rico Civil Registry (1885+), Spanish colonial archives via PARES | Spanish, colonial-era records overlap with Spain |

### Integration Approach

1. **Store guide references in Family Book config:** Map `birth_country_code` to relevant archive guides
2. **Surface during research sessions:** When researching a person born in RU, automatically include `archives/russia-ukraine.md` as context for the research prompt
3. **Pre-fill search targets:** Russian research should prioritize FamilySearch metric books + VGD.ru. Canadian research should start with LAC census + PRDH. Spanish research should target PARES + FamilySearch Spain.
4. **Language-aware prompting:** For Russian-line research, prompts should:
   - Use Cyrillic name variants (already supported: FB has Unicode name fields)
   - Account for Julian/Gregorian calendar differences pre-1918
   - Apply patronymic naming conventions (FB has `patronymic` field + `name_display_order=patronymic`)
   - Try multiple transliterations (Santos/Tanaka)

### Research Templates by Region

Pre-configure research session templates:

- **"Expand Canadian line"**: Uses tree expansion + canada.md guide, targets LAC census, PRDH for Quebec ancestors
- **"Expand Russian line"**: Uses tree expansion + russia-ukraine.md guide, includes patronymic handling, Cyrillic search variants
- **"Expand Spanish line"**: Uses tree expansion + spain-portugal.md guide, targets PARES, Catholic parish records
- **"Puerto Rico colonial"**: Uses tree expansion + both spain-portugal.md and mexico-latin-america.md, bridges colonial and post-colonial records

---

## 7. DNA Analysis Integration

### Current State

autoresearch prompt 12 (`dna-chromosome-analysis.md`) handles:
- Parsing per-chromosome ancestry composition data (23andMe CSV)
- Maternal vs paternal segment assignment
- Cross-referencing genetic patterns against documented family trees
- Confidence-rated chromosome painting

### Family Book Integration Points

| DNA Feature | FB Integration | Model Change |
|---|---|---|
| Ancestry composition percentages | Display on Person profile for tested members | `Person.dna_provider`, `Person.dna_composition` (JSON) |
| Chromosome painting | Separate research artifact, not core FB data | Store in ResearchNote |
| Segment-ancestor mapping | Links genetic segments to documented ancestors | ResearchNote with `kind=dna_mapping` |
| Ethnicity estimates | Could display as supplementary info on Person card | `Person.dna_composition` JSON field |

### Privacy Constraints

DNA data is the most sensitive category:
- **Never send raw genetic data to external services during research**
- DNA CSVs stored in `/data/research/dna/` with restricted access
- Only aggregate composition (e.g., "42% Eastern European") displayed in UI
- Chromosome-level data visible only to the tested person + admin
- DNA findings follow the same proposal->review->accept pipeline

### Practical Priority

DNA integration is **Tier 3**. It requires:
1. A family member to have taken a DNA test and exported results
2. Enough documented tree depth to make segment mapping meaningful
3. Additional UI for chromosome painting visualization

Defer until the core research loop (Tiers 1-2) is working.

---

## 8. Privacy Considerations

### What Data Leaves the System During Research

| Data Flow | What Moves | Where It Goes | Risk Level |
|---|---|---|---|
| **Vault export** | Names, dates, places, relationships | Local filesystem (`/data/research/vault/`) | None - stays on server |
| **Web searches** (autoresearch prompts) | Search queries containing ancestor names + dates + locations | Google, FamilySearch, FindAGrave, etc. | **Medium** - search queries are logged by providers |
| **AI processing** | Vault content sent to Claude API for prompt execution | Anthropic API | **Medium** - subject to Anthropic's data policies |
| **Archive access** | Login credentials if accessing paid archives | Ancestry, MyHeritage, etc. | **Low** - standard account usage |

### Mitigations

1. **No living persons in research prompts by default.** Only research deceased ancestors or persons explicitly flagged for research by admin. The `is_living` flag controls this.
2. **Redact root person.** The root person (Alex's daughter) is always redacted per existing FB rules. Research prompts never include root person data.
3. **Search query minimization.** Prompts should use the minimum information needed: "Ivan Santos born ~1920 Minsk" not "Ivan Santos son of Yuki Tanaka who is the maternal grandmother of [root person]."
4. **Local-first architecture.** The vault lives on the FB server. autoresearch runs as a local process (see Section 9). No vault data is uploaded to cloud storage.
5. **Audit trail.** Every research session logs what data was exported, what searches were performed, and what was found. `ResearchSession` + `AuditLog` provide full traceability.
6. **API key scope.** If autoresearch uses the Agent API, it gets a scoped key (`scope=extended` at most). It cannot access household/emergency contact info.

### Anthropic API Data Policy

When autoresearch prompts run through Claude Code:
- Claude API requests are not used for training (per Anthropic's commercial terms)
- Vault content is processed in-context only
- No persistent storage of family data on Anthropic's side

**Recommendation:** Add a `/admin/research/privacy` page explaining what data flows where, so the admin (Alex) can make informed decisions before each research session.

---

## 9. Technical Architecture

### Recommended: Sidecar Process

autoresearch runs as a **sidecar service** alongside the Family Book container, not embedded in the FastAPI app or as a plugin.

```
┌─────────────────────────────────────────────────┐
│  Docker Compose                                  │
│                                                  │
│  ┌──────────────┐    ┌────────────────────────┐ │
│  │ Family Book   │    │ Research Runner         │ │
│  │ (FastAPI)     │◄──►│ (Python worker)         │ │
│  │               │    │                         │ │
│  │ SQLite DB     │    │ - Vault export/import   │ │
│  │ /data/        │    │ - Prompt execution      │ │
│  │               │    │ - Diff engine           │ │
│  │ Agent API     │    │ - Proposal generator    │ │
│  │ Admin UI      │    │                         │ │
│  └──────┬───────┘    └────────┬───────────────┘ │
│         │                     │                  │
│         └──────┬──────────────┘                  │
│                │                                 │
│         ┌──────▼───────┐                         │
│         │ /data/research/ │                      │
│         │ (shared volume) │                      │
│         └──────────────┘                         │
└─────────────────────────────────────────────────┘
```

### Why Sidecar, Not Embedded

| Option | Pros | Cons |
|---|---|---|
| **Embedded (in FastAPI)** | Simple deployment, shared DB access | Research sessions are long-running (minutes to hours). Blocks web workers. Claude API calls don't belong in a request/response cycle. |
| **Plugin (loaded at runtime)** | Modular | autoresearch is a prompt system, not a Python library. No plugin API to hook into. |
| **Sidecar (separate process)** | Isolated. Can run research without affecting web performance. Natural boundary for the vault filesystem. Can be scaled independently. | Needs IPC mechanism. Slightly more complex deployment. |

### Communication: Family Book <-> Research Runner

**Option A: Shared SQLite + filesystem (recommended for v1)**
- Research Runner reads/writes `/data/research/` for vault files
- Research Runner writes `ResearchSession` and `ResearchProposal` directly to SQLite (WAL mode supports concurrent readers)
- Family Book polls for completed sessions or uses filesystem watch

**Option B: Agent API + webhook (for future)**
- Research Runner uses the Agent API to read family data
- Research Runner posts proposals back via a new `/api/admin/research/proposals` endpoint
- Cleaner separation, but more HTTP overhead

### Research Runner Implementation

```python
# app/research/runner.py (sidecar entry point)

class ResearchRunner:
    def __init__(self, db_path: str, vault_base: str):
        self.db = connect(db_path)
        self.vault_base = vault_base

    async def run_session(self, session_id: UUID):
        session = self.get_session(session_id)

        # 1. Export vault
        vault_path = self.export_vault(session)

        # 2. Prepare prompt with country-specific context
        prompt = self.build_prompt(session, vault_path)

        # 3. Execute via Claude Code subprocess
        result = await self.execute_prompt(prompt, vault_path)

        # 4. Diff and generate proposals
        proposals = self.diff_and_propose(session, vault_path)

        # 5. Write proposals to DB
        self.save_proposals(session, proposals)

        # 6. Mark session complete
        self.complete_session(session)
```

### Prompt Execution

Two options for running autoresearch prompts:

1. **Claude Code subprocess** (recommended): Shell out to `claude` CLI with the prompt file. autoresearch is designed for Claude Code's `/autoresearch` command. This preserves the tool's intended execution model.

2. **Direct Anthropic API**: Call Claude API directly with the prompt content + vault context. More control, but loses Claude Code's tool-use capabilities (web search, file editing).

Recommendation: Start with Claude Code subprocess. It's what autoresearch was built for.

### Deployment

Add to `docker-compose.yml`:

```yaml
research-runner:
  build:
    context: .
    dockerfile: Dockerfile.research
  volumes:
    - family-data:/data
  environment:
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
  depends_on:
    - family-book
```

The research runner shares the `/data` volume for SQLite access and vault storage.

---

## 10. Phased Implementation Plan

### Phase 1: Foundation (S)

**Goal:** Export Family Book data to autoresearch vault format. Manual research via Claude Code.

- [ ] Add `ai_research` to source enums (Person, ParentChild, Partnership)
- [ ] Create `ResearchSession` and `ResearchProposal` models + Alembic migration
- [ ] Build vault exporter (`app/services/research_export.py`):
  - Person -> person.md with YAML frontmatter
  - Family_Tree.md from graph
  - Open_Questions.md from confidence gaps
  - Timeline.md from dates
- [ ] Build vault importer / diff engine (`app/services/research_import.py`):
  - Compare pre/post vault snapshots
  - Parse changes into ResearchProposal records
- [ ] Admin can manually: export vault, run autoresearch in Claude Code, then import results

**Outcome:** Working research loop, fully manual. Validates data model mapping.

### Phase 2: Review Queue (S)

**Goal:** Admin can review and accept/reject research proposals in the UI.

- [ ] `/admin/research` dashboard page (HTMX)
- [ ] `/admin/research/{session_id}/review` proposal review queue
- [ ] Accept/reject/defer/edit-and-accept actions
- [ ] Accepted proposals create/update DB records with proper source tracking
- [ ] AuditLog entries for all research-originated changes

**Outcome:** Complete human-in-the-loop pipeline. No auto-application of findings.

### Phase 3: One-Click Research (M)

**Goal:** "Research This Person" button triggers research sessions from the UI.

- [ ] Research Runner sidecar service
- [ ] Person profile action: "Research This Person" with prompt selection
- [ ] Scope selection (person only, ancestors, branch)
- [ ] Country-specific guide auto-selection based on `birth_country_code`
- [ ] Session status tracking with notifications on completion
- [ ] Research status indicators on D3 tree (green/yellow/red rings)

**Outcome:** Admin clicks a button, waits, reviews proposals. Full integration.

### Phase 4: Advanced Prompts (M)

**Goal:** Integrate Tier 2 prompts and deeper features.

- [ ] Cross-reference audit (prompt 02) integration
- [ ] Immigration search (prompt 11) with Canada/Russia/Spain templates
- [ ] Open question tracking system (prompt 08)
- [ ] GEDCOM completeness validation (prompt 04) - requires GEDCOM export to be built first
- [ ] Research session templates by region (Canadian line, Russian line, Spanish line, Puerto Rico)

**Outcome:** Full prompt library available. Region-aware research.

### Phase 5: Specialized (L)

**Goal:** DNA integration and advanced research features.

- [ ] DNA composition display on Person profiles
- [ ] Chromosome analysis prompt (12) integration
- [ ] FindAGrave sweep (prompt 03) with memorial linking
- [ ] OCR pipeline for scanned family documents
- [ ] Oral history protocol integration (transcription -> Person bio + sources)

**Outcome:** Complete autoresearch integration. Every prompt available through Family Book.

---

## Effort Key

| Size | Meaning |
|---|---|
| S | A focused session of work |
| M | Multiple sessions, some complexity |
| L | Significant effort, multiple components |

---

## Open Questions

1. **Anthropic API costs:** Each research session consumes Claude API tokens. At 12 prompts x 8 iterations each, a full research sweep could use significant context. Need to estimate per-session cost.
2. **Rate limiting:** Should research sessions be queued (one at a time) or can they run concurrently? SQLite WAL supports concurrent reads but only one writer.
3. **Prompt versioning:** autoresearch is an external repo. How do we track which prompt version was used for each session? Pin to a git commit hash.
4. **Vault format stability:** If autoresearch changes its vault template format, the exporter/importer needs updating. Monitor the repo for breaking changes.
5. **GEDCOM timeline:** Several prompts (04, and the export side of the research loop) benefit from GEDCOM support. Should GEDCOM import/export be prioritized to unlock these?
