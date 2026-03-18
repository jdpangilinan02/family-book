# Codex Phase 1 Review

Scope: review of the Phase 1 implementation tracked in commit `c0c79d5`, limited to the files under `app/` that existed in that commit. I did not review the in-progress Phase 2/3 workspace additions under `app/backup`, `app/inbound`, `app/matrix`, `app/middleware`, or `app/pwa`.

## Findings

### High

1. Hidden people leak through `/api/tree` relationship IDs.
   - Files: `app/routes/tree.py:30-48`
   - Problem: the endpoint filters hidden people out of the `persons` list, but returns every `ParentChild` and `Partnership` row without filtering. A non-admin can infer the existence and IDs of hidden people from `parent_id`, `child_id`, `person_a_id`, and `person_b_id`.
   - Impact: privacy breach / IDOR-style leakage for hidden records.
   - Coverage added: `tests/test_phase1_edge_cases.py::test_tree_omits_hidden_person_relationships` (`xfail`)

2. Duplicate partnerships are not actually prevented when `start_date` is `NULL`.
   - Files: `app/models/relationships.py:101-108`, `app/routes/relationships.py:79-120`
   - Problem: dedup depends on a SQLite `UNIQUE(person_a_id, person_b_id, kind, start_date)` constraint. In SQLite, `NULL` values do not compare equal for `UNIQUE`, so duplicate active partnerships with no `start_date` are allowed.
   - Impact: the graph can contain duplicate spouse/partner edges even though the route claims to reject them.
   - Coverage added: `tests/test_phase1_edge_cases.py::test_duplicate_partnership_with_null_start_date_is_rejected` (`xfail`)

3. The root person's real name is still searchable.
   - Files: `app/routes/persons.py:31-37`, `app/schemas.py:108-139`
   - Problem: responses redact the root person correctly, but the search query still matches raw `first_name`, `last_name`, and `nickname`. Searching the real name returns a redacted record and confirms the hidden identity.
   - Impact: privacy leak that violates the "never exposed" redaction rule in practice.
   - Coverage added: `tests/test_phase1_edge_cases.py::test_root_real_name_is_not_searchable` (`xfail`)

4. Suspended users can redeem magic links and receive a fresh session cookie.
   - Files: `app/services/auth_service.py:157-174`, `app/routes/auth_routes.py:112-143`
   - Problem: `validate_magic_link()` checks token validity but does not enforce `account_state == active`. The login route therefore returns `200` and sets a cookie for suspended users; only later requests fail when `validate_session()` rejects them.
   - Impact: broken auth state machine, confusing UX, and unnecessary session issuance to suspended accounts.
   - Coverage added: `tests/test_phase1_edge_cases.py::test_suspended_user_magic_link_login_is_rejected` (`xfail`)

### Medium

5. Magic-link tokens are written to application logs in plaintext.
   - Files: `app/routes/auth_routes.py:100-107`
   - Problem: the full bearer token is logged at `INFO` level.
   - Impact: anyone with log access can authenticate as the user until the token expires.

6. Invite tokens are stored in plaintext while session and magic-link tokens are hashed.
   - Files: `app/services/auth_service.py:102-117`, `app/models/auth.py:40-48`
   - Problem: unclaimed invite links can be replayed directly from database contents or backups.
   - Impact: weaker token-handling posture than the rest of the auth system.

7. Relationship integrity checks stop at self-reference and do not prevent ancestry cycles.
   - Files: `app/routes/relationships.py:24-61`, `app/models/relationships.py:55-58`
   - Problem: `A -> B` and `B -> A` (or longer cycles) are currently accepted.
   - Impact: corrupt family graph semantics and future traversal bugs.
   - Coverage added: `tests/test_phase1_edge_cases.py::test_create_parent_child_rejects_circular_relationship` (`xfail`)

8. Person validation is too weak for user-facing data.
   - Files: `app/schemas.py:7-64`, `app/routes/persons.py:64-142`
   - Problem: blank names are accepted, enum-like fields are plain strings, and `MagicLinkRequest.email` is not validated despite importing `EmailStr`.
   - Impact: malformed display names, inconsistent enum values, and weaker input hygiene than intended.
   - Coverage added:
     - `tests/test_phase1_edge_cases.py::test_create_person_rejects_empty_names` (`xfail`)
     - `tests/test_phase1_edge_cases.py::test_create_person_rejects_very_long_first_name`
     - `tests/test_phase1_edge_cases.py::test_create_person_accepts_unicode_names`

9. Phase 1 has no HTML login page or redirect-based anonymous UX.
   - Files: `app/main.py` in commit `c0c79d5` only includes the five JSON routers at `app/main.py:33-37`; `app/templates/` and `app/static/` are empty.
   - Problem: `/login`, page routes, and redirect-to-login behavior requested by the spec/UI workflow are absent.
   - Impact: browser smoke tests for login form presence and protected-route redirects fail against the shipped Phase 1 app.
   - Coverage added: `tests/ui/agent-browser-tests.sh`

## Security Review

- Path traversal in media serving:
  - No active media-serving route exists in Phase 1, so I did not find a current path traversal primitive.
  - Separate gap: the authenticated media endpoint required by the spec is not implemented yet.

- IDOR:
  - Confirmed issue: hidden people leak through `/api/tree` relationship IDs.
  - No separate cross-user write IDOR found in Phase 1 mutations; person updates are self-or-admin and relationship writes are admin-only.

- Token leakage in responses:
  - I did not find raw session or magic-link tokens returned in normal HTTP JSON responses.
  - I did find raw magic-link tokens leaking to logs, which is operationally equivalent to credential exposure.

- Missing auth checks:
  - No missing auth checks found on the shipped Phase 1 JSON data endpoints.
  - Public endpoints appear intentional: `/health`, `/invite/{token}`, `/invite/{token}/claim`, `/auth/magic-link`, `/auth/magic-link/{token}`, `/auth/logout`.

- SQL injection via search/filter params:
  - I did not find a direct SQL injection vector in Phase 1. The queries are built through SQLAlchemy expressions rather than string concatenation.
  - Added regression coverage for injection-style payloads in `search` and `branch`.

## Test Additions

- New backend coverage: `tests/test_phase1_edge_cases.py`
- New browser smoke test: `tests/ui/agent-browser-tests.sh`
- New Phase 1-only UI app entrypoint: `tests/ui/phase1_app.py`

`xfail` tests in the new backend file represent confirmed Phase 1 defects, not flaky checks.
