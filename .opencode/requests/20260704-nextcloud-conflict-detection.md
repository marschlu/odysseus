---
id: 20260704-nextcloud-conflict-detection
title: "Detect and warn on Nextcloud conflict when local + remote both have changes"
type: feature
status: implemented
priority: normal
service: Frontend
reporter: spec
created: 2026-07-05
---

<!--
  Odysseus request spec.
  Status state machine: draft -> triaged -> approved -> implementing -> implemented -> verified -> done (+ blocked).
  See the `request-workflow` skill for the full pipeline.
-->

# Detect and warn on Nextcloud conflict when local + remote both have changes

## Summary
When the Nextcloud live poll detects remote changes AND the local document has
been modified since the last sync, show a conflict banner instead of
auto-refreshing and silently overwriting local edits.

## Reproduction / Motivation
1. Open a Nextcloud-sourced document in the editor.
2. Make local edits in the textarea (the document's `updated_at` advances on save).
3. Meanwhile, the same file is also modified on the Nextcloud server.
4. The live poll (every 2 min) detects the remote change via `sync-docs`.
5. **Actual:** The editor silently auto-refreshes from Nextcloud, discarding the
   user's local changes with no warning.
6. **Expected:** A conflict banner appears offering the user three options:
   keep local, pull remote, or review differences in the diff view.

**Who benefits:** Any user editing Nextcloud documents in a collaborative or
multi-device environment where concurrent edits are realistic.

## Expected behavior (codebase-anchored)

1. **Live-poll conflict gate.**
   In `_startNextcloudLivePoll` (`static/js/document.js`, line 4237), when
   `result.updated > 0` after a `POST /api/nextcloud/sync-docs` call, the
   handler currently auto-refreshes unconditionally (lines 4263–4278). It must
   first fetch the full document from `GET /api/document/{id}` to obtain the
   authoritative `updated_at` and `nextcloud_synced_at` timestamps, then compare
   them:
   - If **remote-only** changes (`updated_at <= nextcloud_synced_at`): keep the
     existing auto-refresh path (current behavior).
   - If **both local and remote** changes (`updated_at > nextcloud_synced_at`):
     **skip** the auto-refresh and show a **conflict banner** instead.

2. **Conflict banner with three actions.**
   Extend `_showNextcloudUpdateBanner` (`static/js/document.js`, line 4289) with
   a new `opts.conflict` mode. The banner text: *"File changed both locally and
   on Nextcloud — review before syncing."* Three action buttons:
   - **Keep local** — dismiss the banner, stop the live poll for this document
     (`_stopNextcloudLivePoll`), take no further action.
   - **Pull remote** — fetch the latest content from
     `GET /api/document/{id}`, overwrite the editor textarea and cached `docs`
     map entry, then dismiss the banner.
   - **Review changes** — enter the existing diff mode via `enterDiffMode`
     (`static/js/document.js`, line 8186) showing `oldContent =` the current
     local content vs `newContent =` the freshly-fetched remote content, then
     dismiss the banner and stop the live poll for this document.

3. **Timestamp source.**
   The full document API response includes both timestamps via `_doc_to_dict`
   (`routes/document_helpers.py`, lines 57 and 68), which serializes:
   - `updated_at` (from the `TimestampMixin` in `core/database.py`, line 32 —
     auto-bumped on every row update via `onupdate=utcnow_naive`)
   - `nextcloud_synced_at` (from the `Document` model, `core/database.py`, line
     246 — explicitly set by `src/nextcloud_sync.py`, line 223, only when sync
     pulls new remote content)

4. **Cached `docs` map extension.**
   The `docs` Map currently stores `nextcloud_synced_at` (line 7016) but not
   `updated_at`. Add `updated_at` to the cached entry (around line 7016–7017) so
   a quick local check is possible without an extra fetch. When the save
   response returns `/api/document/{id}` PUT (line 9052–9058), update the cached
   `updated_at` as well.

5. **No polling while conflict is unresolved.**
   The live poll must not re-fire `sync-docs` while a conflict banner is
   displayed. The existing guard at line 4250
   (`document.getElementById('nc-update-banner')`) already handles this — the
   conflict banner reuses the same `nc-update-banner` id.

### Evidence

| Source | File | Symbol | Line |
|--------|------|--------|------|
| Live poll handler | `static/js/document.js` | `_startNextcloudLivePoll` | 4237 |
| Existing banner builder | `static/js/document.js` | `_showNextcloudUpdateBanner` | 4289 |
| Diff mode (existing) | `static/js/document.js` | `enterDiffMode` | 8186 |
| Doc serializer (timestamps) | `routes/document_helpers.py` | `_doc_to_dict` | 46 |
| `updated_at` auto-bump | `core/database.py` | `TimestampMixin.updated_at` | 32 |
| `nextcloud_synced_at` column | `core/database.py` | `Document.nextcloud_synced_at` | 246 |
| Sync writes `synced_at` | `src/nextcloud_sync.py` | `sync_nextcloud_documents` | 223 |
| docs Map definition | `static/js/document.js` | `const docs = new Map()` | 127 |
| docs Map `nextcloud_synced_at` | `static/js/document.js` | `_cacheDoc` / `docs.set` | 7016 |
| Document save handler | `static/js/document.js` | `saveDocument` | 9015 |

## Codebase research log
- **2026-07-05 — @triage evidence verification.** All citations confirmed against
  the live codebase (`static/js/document.js`, `routes/document_helpers.py`,
  `core/database.py`, `src/nextcloud_sync.py`):
  - `_startNextcloudLivePoll` (line 4237): already fetches `GET /api/document/{id}`
    at line 4265 re-reading `full.nextcloud_synced_at`, but does NOT compare
    `full.updated_at` — unconditionally refreshes. The conflict gate is the missing
    piece.
  - `_showNextcloudUpdateBanner` (line 4289): handles `opts.autoUpdated` and a
    generic `else` branch with a "Refresh" button. No `opts.conflict` mode exists yet.
  - `enterDiffMode` (line 8186): accepts `oldContent, newContent` — perfect fit for
    the "Review changes" action.
  - `_doc_to_dict` (line 46): serializes both `updated_at` (line 57) and
    `nextcloud_synced_at` (line 68). No backend changes needed.
  - `TimestampMixin.updated_at` (line 32 core/database.py): `onupdate=utcnow_naive`
    confirms auto-bump on every row update.
  - `Document.nextcloud_synced_at` (line 246 core/database.py): `DateTime, nullable`.
  - `sync_nextcloud_documents` (line 223 src/nextcloud_sync.py): sets
    `doc.nextcloud_synced_at = now` only when pulling remote changes.
  - `docs.set` at line 6996 (`addDocToTabs`): stores `nextcloud_synced_at` but
    not `updated_at` — the cache extension part of this spec is correct.
  - `saveDocument` (line 9015): after a successful PUT (lines 9056–9058), updates
    `docs` map with `version` and `content` but not `updated_at`.
  - Minor note: the Implementation Plan step 2 says "Fetch GET /api/document/{id}"
    but that fetch already exists at line 4265. Implementation only needs to **add
    the timestamp comparison** to the existing fetch result, not add a new request.
  No `TODO(research)` markers remain. Evidence is sufficient for implementation.

## Acceptance criteria
- [x] When live poll detects remote changes on a Nextcloud doc that has **no** local
      modifications (`updated_at <= nextcloud_synced_at`), the existing auto-refresh
      behavior is unchanged and the info banner still appears.
- [x] When live poll detects remote changes on a Nextcloud doc that **has** local
      modifications (`updated_at > nextcloud_synced_at`), the editor does **not**
      auto-refresh. A conflict banner appears instead.
- [x] Conflict banner shows the text: *"File changed both locally and on Nextcloud —
      review before syncing."*
- [x] Conflict banner has three buttons: "Keep local", "Pull remote", "Review changes".
- [x] "Keep local" dismisses the banner and stops the live poll for that document.
- [x] "Pull remote" fetches the latest remote content and updates the editor + `docs`
      cache, then dismisses the banner.
- [x] "Review changes" opens the existing diff mode comparing local (current) content
      against the freshly fetched remote content, dismisses the banner, and stops the
      live poll.
- [x] While a conflict banner is displayed, the live poll does not fire additional
      sync requests for that document.
- [x] Syntax check passes: `node --check static/js/document.js`
- [x] No Unicode emoji in any new UI text or SVG; existing SVG icon conventions reused.
- [x] Dark theme preserved; banner reuses existing CSS variables (`--fg`, `--bg`,
      `--red`, `--accent`).

## Implementation plan
1. In `_cacheDoc`/`docs.set` (~line 7016–7017 in `static/js/document.js`), add an
   `updated_at` field to the cached map entry, populated from the API response.
   Also update the cached `updated_at` in `saveDocument` after a successful PUT
   (line 9056–9058).
2. Modify the `result.updated > 0` branch in `_startNextcloudLivePoll`
   (~line 4263–4278):
   - Fetch `GET /api/document/{doc.id}` to get `full.updated_at` and
     `full.nextcloud_synced_at`.
   - Compare: if `new Date(full.updated_at) > new Date(full.nextcloud_synced_at)`,
     call `_showNextcloudUpdateBanner(doc, { conflict: true, remoteContent:
     full.current_content })` instead of auto-refreshing.
   - Otherwise (remote-only), proceed with the existing auto-refresh path.
3. Extend `_showNextcloudUpdateBanner` with a new `opts.conflict` branch that
   renders the three-action conflict banner. Reuse the existing banner styling
   pattern (line 4294–4354) and button conventions.
4. The "Review changes" button calls `enterDiffMode(localContent,
   opts.remoteContent)` where `localContent` is the current textarea value.
5. **No backend changes needed.** The `updated_at` and `nextcloud_synced_at`
   timestamps are already returned by the existing document API.

## Risks / trade-offs
- **Extra fetch per poll hit.** Each time `sync-docs` reports updates, an
  additional `GET /api/document/{id}` call is needed to get the authoritative
  timestamps. This is only ~one extra HTTP call every 2 minutes per active
  Nextcloud doc — negligible.
- **Timestamp skew.** `updated_at` and `nextcloud_synced_at` are both server-side
  UTC timestamps from the same database, so no clock-skew issues.
- **Racy saves.** A user typing rapidly while the poll fires could create a race
  where the save (`updated_at` bump) happens between the timestamp check and the
  banner render. This is acceptable — the worst case is a false-positive
  conflict, which is still far better than silent overwrite.

## Definition of Done
<!-- Inherited checklist; `qa` ticks these before flipping status to `verified`. -->
- [ ] `python -m pytest` green (add/extend tests for changed behavior)
- [ ] `python -m py_compile` clean on changed Python files
- [ ] `node --check` clean on changed JS files (if applicable)
- [ ] Path constants from `src/constants.py` used (no hardcoded paths)
- [ ] `internal_api_base()` used for loopback URLs (no hardcoded `localhost:7000`)
- [ ] No Unicode emoji in UI changes (inline SVG or plain text instead)
- [ ] Dark theme preserved; existing CSS variables reused
- [ ] No parallel component patterns — extended existing widgets where applicable
- [ ] Conventional Commits format ready (`type(scope): summary`)
- [ ] Branch from `dev`; PR targets `dev`
- [ ] Relevant docs updated
- [ ] This spec's `status` advanced and `Changelog` updated

## Changelog
- 2026-07-05 — created (draft) — @spec
- 2026-07-05 — triaged (evidence: sufficient) — @triage
- 2026-07-05 — implemented on `feat/nextcloud-conflict-detection` — @implement
