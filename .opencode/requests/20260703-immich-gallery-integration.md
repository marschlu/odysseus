---
id: 20260703-immich-gallery-integration
title: Integrate Immich photo server into Odysseus gallery
type: feature
status: triaged
priority: normal
service: Routes
reporter: spec
created: 2026-07-03
---

<!--
  Odysseus request spec. Copy this file to <id>-<slug>.md (e.g. 20260627-add-search-filter.md)
  and fill it in. Keep the YAML frontmatter above as the FIRST thing in the file — the `flow`
  agent parses `status` from it. Status state machine:
  draft -> triaged -> approved -> implementing -> implemented -> verified -> done (+ blocked).
  See the `request-workflow` skill for the full pipeline.
-->

# Integrate Immich photo server into Odysseus gallery

## Summary
Add Immich (self-hosted photo/video management server) as a gallery source in Odysseus, letting users browse, preview, and optionally import photos and albums from their Immich instance directly within the existing Odysseus gallery UI.

## Reproduction / Motivation
The Odysseus gallery currently stores and displays locally-generated images and uploaded photos. Users who already run Immich as their photo management backend want to browse their Immich library without leaving Odysseus. This is analogous to the existing Nextcloud Files integration (`routes/nextcloud_routes.py`, `src/nextcloud_client.py`) which lets Odysseus browse a remote Nextcloud server inline.

**Who benefits:** Self-hosting users running both Odysseus and Immich who want a unified gallery experience without duplicating their photo storage.

## Expected behavior (codebase-anchored)
- Users can configure one or more Immich server connections (URL + API key) in Odysseus, stored per-user in the same prefs mechanism used for Nextcloud accounts. Evidence: `routes/prefs_routes.py` `_load_for_user` / `_save_for_user` · line 32 / 45; `routes/nextcloud_routes.py` `_load_accounts` / `_save_accounts` · line 42 / 46.
- The gallery can list Immich photos, albums, and people, and display them alongside local gallery items. Evidence: `routes/gallery/gallery_routes.py` `_gallery_image_path` · line 55; frontend `static/js/gallery.js` `_fetchLibrary` · line 75.
- Immich credentials (API key) are encrypted at rest and never returned by any endpoint. Evidence: `routes/nextcloud_routes.py` `_redact` · line 58; `src/secret_storage.py` encrypt/decrypt pattern.
- Owner-scope isolation: each user's Immich connections are separate. Evidence: `routes/gallery/gallery_helpers.py` `_owner_filter` · line 130; `routes/nextcloud_routes.py` `_require_owner` · line 31.
- Immich items are clearly distinguished from locally-stored items (e.g., a source badge or column). Evidence: `core/database.py` `GalleryImage.source_nextcloud_account` · line 316; `routes/gallery/gallery_helpers.py` `_image_to_dict` includes `source_nextcloud_account` · line 123.
- When Immich server is unreachable, the gallery degrades gracefully (shows error, doesn't crash the whole gallery). Evidence: `src/nextcloud_client.py` `NextcloudError` · line 60; `routes/nextcloud_routes.py` `_map_nextcloud_error` · line 90.

## Codebase research log
**Investigated by triage** (2026-07-03):

### Immich API endpoint correction
The spec originally referenced `/api/photos`, `/api/albums`, and `/api/shared-libraries`. Research against the Immich OpenAPI spec (main branch) found:
- **`/api/photos` → `/assets`**: Immich calls photos "assets". Endpoints: `GET /assets` (list), `GET /assets/{id}` (detail), `POST /assets` (upload), etc.
- **`/api/albums` → `/albums`**: ✅ Already correct.
- **`/api/shared-libraries` → does not exist**: Two separate concepts exist: `GET /libraries` (external scan libraries, admin-only) and `GET /shared-links` (public share links). The correct endpoint for browsing shared content is `/shared-links`.

### Nextcloud integration pattern (current state)
- **`routes/nextcloud_routes.py`**: Account CRUD at `/accounts` (GET/POST/PUT/DELETE), `POST /test` (connection test), `GET /list` (browse), `GET /stat` (stat), `GET /file` (download), `POST /open-in-asset` (import into Odysseus). The `open-in-asset` endpoint is the key pattern to follow for optional import.
- **`src/nextcloud_client.py`**: Full read-write client (ping, list_dir, stat, get_file, put_file, mkcol, delete). Routes only expose read operations; write methods available for future sync.
- **`core/database.py`**: `GalleryImage` model has `source_nextcloud_account` (L316) and `source_nextcloud_path` (L317) columns with migration at L857–869. The `Document` model has richer tracking (sync_status, synced_at, sync_error) — GalleryImage does not.
- **`routes/gallery/gallery_helpers.py`**: `_image_to_dict` (L96) includes `source_nextcloud_account` and `source_nextcloud_path` via `getattr` (defensive against older DB states).

### Pattern to follow
The Nextcloud integration uses **virtual browsing with optional import via `open-in-asset`**. The Immich integration should follow the same pattern: virtual by default (proxy on-demand), optional import that stamps provenance columns on the `GalleryImage` model. The `open-in-asset` endpoint at `routes/nextcloud_routes.py` L268 provides the deduplication and routing pattern.

## Acceptance criteria
- [ ] User can add an Immich server connection (base URL + API key) via a settings UI, stored per-user in prefs alongside existing Nextcloud accounts.
- [ ] User can remove an Immich server connection; the API key is not returned in any response.
- [ ] Gallery "Photos" tab can fetch and display photos from a configured Immich instance, paginated, with thumbnails.
- [ ] Gallery "Albums" tab can fetch and display albums from Immich; clicking an album filters the photos to that album.
- [ ] Immich-sourced photos display a visual indicator (e.g., source badge) distinguishing them from locally-stored gallery images.
- [ ] Video items from Immich are shown in the gallery grid with a video indicator (not silently skipped).
- [ ] If the Immich server is down or returns an error, the gallery shows an error message for that source but continues to display local photos.
- [ ] Owner-scope isolation: in multi-user mode, User A cannot see User B's Immich connections or their photos.
- [ ] Immich API calls are made through the SSRF guard (`src/url_safety.check_outbound_url`), same as Nextcloud.
- [ ] Connection test endpoint validates the Immich URL and API key before saving.

## Implementation plan
1. **Backend — Immich client** (`src/immich_client.py`): HTTP client for Immich REST API, modeled after `src/nextcloud_client.py`. Handles authentication (X-Api-Key header), SSRF validation, and error mapping. Key endpoints: `/assets` (list/detail photos — Immich calls them "assets", not "photos"), `/albums` (list albums, album details, album assets), `/shared-links` (shared links — not "shared-libraries"). See Codebase research log for endpoint details.
2. **Backend — Immich routes** (`routes/immich_routes.py`): Account management (CRUD) and proxy endpoints for fetching Immich data. Modeled after `routes/nextcloud_routes.py`. Prefix: `/api/immich`.
3. **Backend — Gallery extension** (`routes/gallery/gallery_routes.py`): Extend the `/api/gallery/library` endpoint to optionally include Immich-sourced items. Add `source_immich_account` column to `GalleryImage` (or create a separate virtual source — see trade-offs below).
4. **Database — New columns** (`core/database.py`): Add `source_immich_account` and `source_immich_id` columns to `GalleryImage`, with migration in `_migrate_add_immich_gallery_columns()`.
5. **Frontend — Gallery extension** (`static/js/gallery.js`): Add Immich source selector/filter in gallery toolbar; render Immich-sourced items with a source badge; handle video items from Immich.
6. **Frontend — Settings** (`static/js/settings.js`): Add Immich account configuration UI in the same section as Nextcloud accounts.
7. **Tests**: Route tests for Immich endpoints (owner-scope, error handling), gallery tests for mixed-source rendering, client unit tests.

## Risks / trade-offs
- **Virtual vs. imported**: Two approaches — (a) proxy Immich photos on-demand (virtual, no local storage, always up-to-date) or (b) import Immich photos into Odysseus local storage (cached, but duplicates data). The Nextcloud pattern uses virtual browsing with optional import via `open-in-asset`. We should follow the same pattern: virtual by default, optional import.
- **Video support**: Immich serves video files; the current gallery is image-centric. Need to decide whether to render video thumbnails, skip videos, or add a video player. At minimum, videos should not crash the gallery.
- **Rate limiting**: Immich has rate limits on its API. Need to respect `X-RateLimit-*` headers and implement backoff in the client.
- **SSRF**: Immich URLs must go through the same SSRF guard as Nextcloud (`src/url_safety.check_outbound_url`).
- **Large libraries**: Immich libraries can have 100K+ photos. The gallery must paginate efficiently and not load everything at once.

## Feasibility / complexity assessment
**Estimated effort: Medium**

The Nextcloud integration is a direct precedent — it solves the same problem (browse a remote file/photo server from Odysseus) with the same patterns (per-user account storage, encrypted credentials, virtual browsing with optional import, SSRF guards). The main differences:

1. **Immich API is REST-based** (not WebDAV), which is simpler to integrate than Nextcloud's XML-heavy WebDAV protocol. The Immich API is well-documented and returns JSON.
2. **Gallery UI already exists** — the frontend work is extending the existing gallery module, not building a new one.
3. **Video support is new** — the current gallery is image-only; Immich serves videos too. This adds scope.

Breakdown:
- Immich client module: ~1-2 days (following Nextcloud client pattern)
- Immich routes + account management: ~1-2 days
- Gallery backend extension (mixed-source listing): ~1-2 days
- Database migration: ~half day
- Frontend gallery extension: ~2-3 days
- Frontend settings UI: ~1 day
- Testing: ~1-2 days
- **Total estimate: ~8-14 developer days**

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
<!-- Append one line per status transition / commit. -->
- 2026-07-03 — created (draft) — @spec
- 2026-07-03 — triaged (evidence: partial — Immich API endpoints corrected via research; Nextcloud pattern verified) — @triage
