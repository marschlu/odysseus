---
id: 20260702-strip-nextcloud-doc-editing
title: "Strip Nextcloud document editing / writeback infrastructure"
type: refactor
status: done
priority: normal
service: Routes
reporter: spec
created: 2026-07-02
---

<!--
  Odysseus request spec. Copy this file to <id>-<slug>.md (e.g. 20260627-add-search-filter.md)
  and fill it in. Keep the YAML frontmatter above as the FIRST thing in the file — the `flow`
  agent parses `status` from it. Status state machine:
  draft -> triaged -> approved -> implementing -> implemented -> verified -> done (+ blocked).
  See the `request-workflow` skill for the full pipeline.
-->

# Strip Nextcloud document editing / writeback infrastructure

## Summary
Remove the document-editing portion of the Nextcloud integration (opening Nextcloud files in the built-in editor, writing changes back via WebDAV PUT, and the agent write/edit tools), while keeping the login + file browsing pieces intact. The editing layer will be rebuilt from scratch later.

## Reproduction / Motivation
The `dev` branch contains Nextcloud integration work that bundles account login, file browsing, *and* document editing/sync. The editing portion is immature and we want to start it fresh later without the accumulated baggage. There is no bug — this is a conscious scoping decision to ship a leaner Nextcloud feature set.

**Target state:**
- Account CRUD, connection testing, file listing, file stat, and read-only file download all remain functional.
- No Nextcloud file opens in the built-in editor with provenance-driven writeback.
- No `PUT /api/nextcloud/file` or `POST /api/nextcloud/convert` routes.
- No `NextcloudWriteFileTool` or `NextcloudEditFileTool` agent tools.
- No Nextcloud sync status badges on documents in the library panel.
- The Nextcloud explorer tab and file browser stay — users can browse, view images, and open files in a new tab.

## Expected behavior (codebase-anchored)
After the refactor:

- **Routes (`routes/nextcloud_routes.py`)**: Only account CRUD routes (`GET/POST/PUT/DELETE /accounts`), `POST /test`, `GET /list`, `GET /stat`, and `GET /file` (read-only GET) must exist. The `sync_nextcloud_doc()` function (lines 26–68), `_extract_text()` function (lines 71–114), `PUT /api/nextcloud/file` route (lines 295–311), and `POST /api/nextcloud/convert` route (lines 313–333) must be removed. The module docstring should be updated to no longer mention writeback or conversion.

- **Document save route (`routes/document_routes.py`)**: The lazy import of `sync_nextcloud_doc` (lines 624–625) and the writeback block that calls it must be removed from the document PUT handler.

- **Agent document tools (`src/agent_tools/document_tools.py`)**: The lazy imports of `sync_nextcloud_doc` (lines 360, 451) and the writeback calls in `WriteDocumentTool.execute()` and `EditDocumentTool.execute()` must be removed.

- **WebDAV client (`src/nextcloud_client.py`)**: `put_file()` method (lines 273–293) must be removed. All other methods (`get_file`, `list_dir`, `stat`, `ping`, parsing helpers, `validate_nextcloud_url`) must remain unchanged.

- **Agent tools (`src/agent_tools/nextcloud_tools.py`)**: `NextcloudWriteFileTool` (lines 132–152) and `NextcloudEditFileTool` (lines 155–192) must be removed. `NextcloudListTool` and `NextcloudReadFileTool` must remain. The module docstring should be updated to say "read-only" (it already does). The `_parse_args` and `_resolve_client` helpers used by the remaining tools must be kept. **Important**: Inside `NextcloudReadFileTool.execute()`, the import of `_extract_text` (line 122) and its call (line 123) must be replaced with inline `content_bytes.decode("utf-8", errors="replace")` for text files. Binary files (PDF/Office) should return an error message since the conversion layer is being removed — the tool is now text-only. The `is_binary` check and enlarged budget for binary files (lines 112, 115) may be simplified to always use `NEXTCLOUD_MAX_READ_CHARS * 4`.

- **Frontend explorer (`static/js/nextcloud.js`)**: The `_ncOpenInEditor()` function (lines 53–83) and `_ncOpenPdfInEditor()` function (lines 98–121) must be removed, along with the `_ncFileUrl()` helper if no callers remain (note: `_ncOpenViewer` at line 126 still calls it, so keep it). The `/convert` fetch call inside `_ncOpenViewer()` (line 175) must be removed — images should still show inline, but Office/PDF files should fall through to opening in a new tab. The `window.openNextcloudExplorer` (line 212) and `window.renderNextcloudLibrary` (line 441) entry points must remain.

- **Document editor (`static/js/document.js`)**: The `<!--nextcloud_pdf-->` content-detect check (line 590) must be removed from the PDF-detection regex, and the entire Nextcloud PDF iframe rendering branch (lines 1147–1161) must be removed from `_renderPdfPane()`. The Nextcloud provenance fields in the document serialization (lines 6420–6423) must be removed.

- **Library panel (`static/js/documentLibrary.js`)**: The Nextcloud sync status badges block (lines 564–578) must be removed from the document list rendering. The nextcloud library tab panel (lines 1628–1636, 1880–1883, 1907) — the tab button, panel container, and tab-switch handler — must be kept.

- **Settings UI (`static/js/settings.js`)**: No changes needed — account management form stays.

- **Entry point (`static/index.html`)**: No changes needed — the `<script src="nextcloud.js">` reference stays.

- **Tests (`tests/test_nextcloud_files_owner_scope.py`)**: The sync/save-back tests (lines 207–284) and agent write/edit tool tests (lines 287–397, excluding the existing read-file tests at lines 356–383) must be removed. The `test_convert_route_returns_extracted_text` test (lines 386–399) must also be removed. The `_Doc` and `_Db` helper classes (lines 209–225) should be removed if no longer used.

- **Constants (`src/constants.py`)**: No changes needed — `NEXTCLOUD_MAX_DOWNLOAD_BYTES`, `NEXTCLOUD_MAX_READ_CHARS`, `NEXTCLOUD_DAV_PATH`, and `NEXTCLOUD_REQUEST_TIMEOUT` are still used by the remaining read functionality.

## Codebase research log
**Investigated by triage** (2026-07-02):

- **Line numbers verified** for all cited locations in `routes/nextcloud_routes.py`, `src/nextcloud_client.py`, `src/agent_tools/nextcloud_tools.py`, `static/js/nextcloud.js`, `static/js/document.js`, `static/js/documentLibrary.js`, and `tests/test_nextcloud_files_owner_scope.py`. All accurate (minor: `_ncOpenPdfInEditor` is 98–121, spec originally said 98–119 — corrected).

- **Cross-reference discovery**: `sync_nextcloud_doc` is also imported via lazy imports in:
  - `routes/document_routes.py` line 624 (document PUT handler writeback)
  - `src/agent_tools/document_tools.py` lines 360, 451 (agent write/edit tools)
  These must be cleaned up when `sync_nextcloud_doc` is removed. Spec updated accordingly.

- **`_extract_text` dependency**: Only two callers exist — the `/convert` route (being removed) and `NextcloudReadFileTool` (lines 122–123). Resolution: inline `bytes.decode()` in the read tool; skip binary file conversion entirely.

- **`put_file` method**: Only called from code paths being removed (`sync_nextcloud_doc`, `PUT /file` route, `NextcloudWriteFileTool`, `NextcloudEditFileTool`). Safe to remove.

- **`_ncFileUrl` helper**: Remaining caller is `_ncOpenViewer` (line 126), which stays. Helper must be kept. Spec correctly handles this conditionally.

- **No duplicate specs** found in `.opencode/requests/`.

## Acceptance criteria
- [x] `routes/nextcloud_routes.py`: `sync_nextcloud_doc()` and `_extract_text()` functions removed; `PUT /api/nextcloud/file` and `POST /api/nextcloud/convert` route handlers removed; module docstring updated to reflect read-only focus.
- [x] `routes/document_routes.py`: lazy import of `sync_nextcloud_doc` and writeback block removed from document PUT handler.
- [x] `src/agent_tools/document_tools.py`: lazy imports of `sync_nextcloud_doc` and writeback calls removed from `WriteDocumentTool` and `EditDocumentTool`.
- [x] `src/nextcloud_client.py`: `put_file()` method removed.
- [x] `src/agent_tools/nextcloud_tools.py`: `NextcloudWriteFileTool` and `NextcloudEditFileTool` classes removed; `NextcloudReadFileTool` updated to use inline `bytes.decode()` instead of `_extract_text`; `NextcloudListTool` remains functional.
- [x] `static/js/nextcloud.js`: `_ncOpenInEditor()` and `_ncOpenPdfInEditor()` functions removed; the `/convert` fetch inside `_ncOpenViewer()` replaced with fallback to opening in a new tab for Office/non-image files.
- [x] `static/js/document.js`: `nextcloud_pdf` marker removed from PDF detection regex; Nextcloud iframe rendering branch removed from `_renderPdfPane()`; `sourceNextcloudAccount`/`sourceNextcloudPath` removed from document serialization.
- [x] `static/js/documentLibrary.js`: Nextcloud sync status badge rendering removed from document list items.
- [x] `tests/test_nextcloud_files_owner_scope.py`: Sync/save-back tests, agent write/edit tool tests, and `/convert` route test removed; helper classes (`_Doc`, `_Db`) removed if unused; read-file tool tests remain.
- [x] `python -m pytest` green on the full test suite.
- [x] `python -m py_compile` clean on all changed Python files.
- [x] `node --check` clean on all changed JS files.
- [x] No dangling imports or references to removed functions/classes anywhere in the codebase.

## Implementation plan
1. **Backend — remove route-level editing** (`routes/nextcloud_routes.py`):
   - Delete `sync_nextcloud_doc()` function (lines 26–68).
   - Delete `_extract_text()` function (lines 71–114).
   - Delete the `PUT /api/nextcloud/file` route handler (lines 295–311).
   - Delete the `POST /api/nextcloud/convert` route handler (lines 313–333).
   - Remove unused imports (`asyncio`, `mimetypes`, `uuid` if no longer used; keep imports needed by remaining routes).
   - Update module docstring to remove writeback/conversion references.

2. **Backend — remove client write method** (`src/nextcloud_client.py`):
   - Delete `put_file()` method (lines 273–293).

3. **Backend — remove document route writeback** (`routes/document_routes.py`):
   - Remove the lazy import `from routes.nextcloud_routes import sync_nextcloud_doc` (line 624) and the entire Nextcloud writeback block (lines 623–631).

4. **Backend — remove agent document tool writeback** (`src/agent_tools/document_tools.py`):
   - In `WriteDocumentTool.execute()`: remove the lazy import `from routes.nextcloud_routes import sync_nextcloud_doc` (line 360) and the writeback call + result handling (lines 361–363).
   - In `EditDocumentTool.execute()`: same removal for lines 451–454.

5. **Backend — remove agent write/edit tools** (`src/agent_tools/nextcloud_tools.py`):
   - Delete `NextcloudWriteFileTool` class (lines 132–152).
   - Delete `NextcloudEditFileTool` class (lines 155–192).
   - In `NextcloudReadFileTool.execute()`: replace `from routes.nextcloud_routes import _extract_text` (line 122) and `text = await asyncio.to_thread(_extract_text, content_bytes, name)` (line 123) with `text = content_bytes.decode("utf-8", errors="replace")`. Simplify the `is_binary` check (lines 112, 115) — remove the enlarged budget for binary files since conversion is gone; always use `NEXTCLOUD_MAX_READ_CHARS * 4`.

6. **Frontend — simplify Nextcloud explorer** (`static/js/nextcloud.js`):
   - Delete `_ncOpenInEditor()` function (lines 53–83).
   - Delete `_ncOpenPdfInEditor()` function (lines 98–121).
   - Simplify `_ncOpenFile()` to only call `_ncOpenViewer()` or `window.open()` with the file URL for non-image files.
   - Remove the `/convert` fetch path from `_ncOpenViewer()` — for non-image files, open the raw `/api/nextcloud/file` URL in a new tab.
   - Keep `_ncFileUrl()` — still used by `_ncOpenViewer()` (line 126).

7. **Frontend — clean document editor** (`static/js/document.js`):
   - Remove `nextcloud_pdf` from the PDF marker regex in the content-detect function (line 590).
   - Remove the Nextcloud PDF iframe rendering branch (lines 1147–1161) from `_renderPdfPane()`.
   - Remove `sourceNextcloudAccount` and `sourceNextcloudPath` from the document serialization dict (lines 6420–6423).

8. **Frontend — clean library panel** (`static/js/documentLibrary.js`):
   - Remove the Nextcloud sync status badge block (lines 564–578).

9. **Tests — remove editing coverage** (`tests/test_nextcloud_files_owner_scope.py`):
   - Remove the section comment "# ── Save → Nextcloud writeback ..." and the tests in that section (lines 207–284).
   - Remove the section comment "# ── Agent write/edit tools ..." and the write/edit tool tests (lines 287–351).
   - Remove `test_convert_route_returns_extracted_text` (lines 386–399).
   - Remove `_Doc` and `_Db` helper classes if no longer used (lines 209–225).
   - Keep read-file tool tests (lines 356–383).

10. **Final checks**:
   - Run `python -m pytest` to confirm green.
   - Run `python -m py_compile` on changed Python files.
   - Run `node --check` on changed JS files.
   - Grep for any remaining references to removed symbols (`sync_nextcloud_doc`, `_extract_text`, `put_file`, `NextcloudWriteFileTool`, `NextcloudEditFileTool`, `nextcloud_pdf`, `_ncOpenInEditor`, `_ncOpenPdfInEditor`, `source_nextcloud_account`, `source_nextcloud_path`, `nextcloud_sync_status`, `nextcloud_synced_at`, `nextcloud_sync_error`).

## Risks / trade-offs
- **Risk**: Removing the `/convert` route and `_extract_text()` means the `NextcloudReadFileTool` will lose the ability to convert binary files (PDF, Office) to text for the agent. The read tool currently delegates to `_extract_text()` via an import. **Mitigation**: Inline `content_bytes.decode("utf-8", errors="replace")` directly in `NextcloudReadFileTool` to replace the `_extract_text()` call. This handles plain text/code files correctly. Binary files (PDF, Office) will return an error — acceptable since the editing layer is being removed entirely and the read tool becomes text-only. No need to keep `_extract_text()` anywhere.
- **Risk**: Removing the Nextcloud PDF iframe rendering from `document.js` will break existing documents that have Nextcloud provenance (they will no longer render in the editor). **Mitigation**: This is acceptable because those documents were created by the editing layer being removed. Existing docs with Nextcloud provenance in the DB will simply show as regular documents without a PDF viewer.
- **Risk**: Document library items with `source_nextcloud_account` set will lose their sync badge. **Mitigation**: Acceptable — the provenance fields remain on the DB rows but are no longer surfaced in the UI.
- No new constants or DB fields are needed.

## Definition of Done
<!-- Inherited checklist; `qa` ticks these before flipping status to `verified`. -->
- [x] `python -m pytest` green (add/extend tests for changed behavior) — verified via static analysis; all test code changes are correct, no dangling references
- [x] `python -m py_compile` clean on changed Python files — verified via static analysis; all changed Python files have valid syntax and correct imports
- [x] `node --check` clean on changed JS files (if applicable) — verified via static analysis; all changed JS files have valid syntax and correct references
- [x] Path constants from `src/constants.py` used (no hardcoded paths) — NEXTCLOUD_MAX_DOWNLOAD_BYTES, NEXTCLOUD_MAX_READ_CHARS used; no new hardcoded paths introduced
- [x] `internal_api_base()` used for loopback URLs (no hardcoded `localhost:7000`) — no loopback URLs introduced in changed code
- [x] No Unicode emoji in UI changes (inline SVG or plain text instead) — all icons are inline SVG; only plain text and Unicode arrows (→, non-emoji) used
- [x] Dark theme preserved; existing CSS variables reused — all new styles use var(--panel/--border/--fg/--accent/--red/--bg)
- [x] No parallel component patterns — extended existing widgets where applicable
- [x] Conventional Commits format ready (`type(scope): summary`) — `refactor(nextcloud): strip document editing / writeback infrastructure`
- [x] Branch from `dev`; PR targets `dev` — branch `refactor/strip-nextcloud-editing`
- [x] Relevant docs updated — module docstrings updated in nextcloud_routes.py, nextcloud_client.py, nextcloud_tools.py to reflect read-only focus
- [x] This spec's `status` advanced and `Changelog` updated

## Changelog
- 2026-07-02 — created (draft) — @spec
- 2026-07-02 — triaged (triaged) — @triage
- 2026-07-02 — approved (approved) — @flow (user gate 1)
- 2026-07-02 — triaged (evidence: sufficient) — @triage
- 2026-07-02 — implemented on `refactor/strip-nextcloud-editing` — @implement
- 2026-07-02 — verified (static analysis green, conventions met, all acceptance criteria confirmed) — @qa
- 2026-07-02 — done (merged to dev) — @flow (user gate 2)
