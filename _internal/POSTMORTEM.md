# Post-mortems

A bug is not properly handled until it has a post-mortem; the post-mortem is what prevents the next occurrence.

---

## B-C1-SECRET-KEY-2026-06-27 — SECRET_KEY boot guard accepts `.env.example` placeholder

| Field | Value |
|---|---|
| **Bug ID** | B-C1-SECRET-KEY-2026-06-27 |
| **Date detected** | 2026-06-27 |
| **Date fixed** | 2026-06-27 |
| **Severity** | SEV1 (latent — caught pre-deploy during boot-guard refactor) |
| **Branch / Fix** | `toonMac` @ commit `562886f` |
| **Author** | narawichswu |
| **Reviewers** | assigned at PR review |

### Summary
The FastAPI backend's boot-time `SECRET_KEY` guard used strict equality against the legacy literal `"change-me-in-production"`. The `.env.example` placeholder evolved to `CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32` (44 chars), which slipped past both the literal check and the 32-char length check, allowing the server to boot with a publicly known JWT signing key.

### Symptom
With a `.env` derived from `.env.example` (operator forgot to override `SECRET_KEY`), the server boots successfully. Any user with read access to the public repo can sign a JWT with the placeholder secret and authenticate as admin. No error log, no alert — silent acceptance.

### Root cause
**Boot-time secret guards validated against a single hardcoded literal rather than the structural shape of a placeholder.**

### Why it produced the symptom
1. `.env.example` line 32 ships `SECRET_KEY=CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32` as the operator-facing template.
2. Operator runs `cp .env.example .env` and forgets to override.
3. `backend/main.py` boot guard checks `settings.SECRET_KEY == "change-me-in-production"`. Strict equality against the **old** 27-char literal fails to match the new 44-char placeholder, so no exception is raised.
4. The 32-char length check passes (44 ≥ 32).
5. Server starts; `backend/auth/jwt.py` signs tokens with `settings.SECRET_KEY`.
6. Attacker reads `.env.example` from the public repo, copies the literal, signs `{sub: "admin", ...}`, JWT verification passes.

### Detection
Caught during a boot-guard refactor on branch `toonMac` (commit `67147f6 debug`). Developer noticed the length check no longer matched the `.env.example` literal and ran a deterministic repro: a throwaway harness that loaded the old check semantics, fed it the new placeholder, and forged a valid admin JWT with `jwt.encode(payload, "CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32", ...)`.

### Why it slipped through
- **No test pinned the boot guard against `.env.example`.** `tests/` had no module-boot tests that read `.env.example` and asserted refusal.
- **Strict equality against a moving literal.** The guard encoded the placeholder as a hardcoded string in source. When the placeholder evolved, the source still checked the old string.
- **No CI check that `settings.SECRET_KEY` cannot be any value present in `.env.example`.** A static assertion would have caught this immediately.
- **No alert on `len(settings.SECRET_KEY) < 32` with a placeholder-shaped value.** The length check passed, so nothing logged.

### Fix
Commit `562886f` on `toonMac`. Replaces the strict-equality check with a two-layer guard via the new helper `_is_placeholder_secret_key`:

- **Denylist** (`_KNOWN_PLACEHOLDER_SECRETS`) — pins known-bad literals so a future placeholder change cannot silently regress.
- **Anchored prefix regex** — catches the `CHANGE_ME…` convention used in operator-facing templates, so new placeholders that follow the same pattern are caught without manual denylist updates.

Both layers are required: regex alone misses unusual literals; denylist alone needs manual maintenance.

### Validation
- `tests/test_secret_key_check.py` — 15 regression cases pinning:
  - Legacy literal still rejected (regression-of-regression guard)
  - New `.env.example` literal rejected (the actual bug)
  - Prefix variants rejected (`CHANGE_ME`, `CHANGE_ME_LATER`, `CHANGE-ME`, `change-me-now`)
  - Substring match anywhere-in-string rejected (prevents false negatives on legitimate passphrases that happen to contain a placeholder fragment)
  - `openssl rand -hex 32` output (64 hex chars) passes
  - Conftest test secret passes (otherwise the suite cannot import `backend.main`)
  - Denylist pins legacy literal so a future refactor cannot silently drop it
- Full suite: **132 passed, 1 skipped**, no regression.

### Action items
- [ ] Remove `SECRET_KEY` literal default from `backend/config.py:18` (replace with empty string; rely on boot guard). **Owner:** narawichswu. **Due:** 2026-07-04.
- [ ] Fix `ADMIN_PASSWORD` / `VIEWER_PASSWORD` defaults in `backend/main.py:330,337` (empty default; refuse to seed if equal to literal). **Owner:** narawichswu. **Due:** 2026-07-04.
- [ ] Generalize placeholder regex to cover `REPLACE-WITH-*`, `YOUR-*`, `MY-*` conventions. **Owner:** narawichswu. **Due:** 2026-07-11.

### Lessons
A boot-time guard that validates a secret by strict equality against a hardcoded literal is **encoding a snapshot of the threat model in source code** — when the threat model moves (placeholder convention changes), the guard silently rots. The structural fix (validate the *shape* of a placeholder, not a specific literal) is what makes the guard future-proof.

### What we'd do differently next time
Add a CI check that reads `.env.example` and asserts that every variable is either absent from any boot guard's denylist OR triggers a guard failure. This would catch placeholder-template drift automatically.

### What we got right
The refactor that surfaced the bug was small and reversible (single commit, full regression suite green). The fix landed with both layers (denylist + regex) instead of just the literal-update shortcut — future placeholders following the same convention are caught without a code change.

### What we'd tell ourselves at the start
"If your boot guard's denylist is the same size as your `.env.example`, the guard is checking the template, not the threat."
