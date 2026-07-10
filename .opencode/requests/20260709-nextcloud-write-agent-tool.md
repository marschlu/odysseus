---
id: REQ-20260709-nextcloud-write-agent-tool
title: "Add nextcloud_write_file agent tool for direct LLM write access"
type: feature
status: verified
priority: normal
service: Agent
reporter: user
created: 2026-07-09
---

# Add nextcloud_write_file agent tool

## Summary
The LLM agent currently has read-only access to Nextcloud via `nextcloud_list` and `nextcloud_read_file`. The `NextcloudClient` already supports `put_file`, `mkcol`, and `delete` (used by the document writeback system), but these aren't exposed as agent-callable tools. The user wants the LLM to be able to write/create/delete files directly on Nextcloud.

## Motivation
The LLM told the user "I can't write to Nextcloud" — which is true for agent tools but not for the system. Adding a `nextcloud_write_file` tool lets the agent:
- Create new files on Nextcloud (e.g. "save this summary to Nextcloud")
- Update existing files (e.g. "update my notes file with this new section")
- Create folders (e.g. "organize these into a new folder")
- Delete files (e.g. "remove the old draft from Nextcloud")

## Expected behavior (codebase-anchored)
- New agent tool `nextcloud_write_file` with actions: `write`, `mkdir`, `delete`
- Reuses existing `NextcloudClient.put_file`, `NextcloudClient.mkcol`, `NextcloudClient.delete`
- Tool registered in `src/agent_tools/__init__.py`, `tool_schemas.py`, `tool_index.py`
- Follows the same pattern as existing `nextcloud_list` and `nextcloud_read_file` tools
- Security: respects the same SSRF guards and path confinement as read tools
- No binary file writing (text only) — binary files go through the document editor flow

## Acceptance criteria
- [x] `nextcloud_write_file` tool with `action` param: `write`, `mkdir`, `delete`
- [x] `write` action: writes `content` string to `path` on Nextcloud (creates or overwrites)
- [x] `mkdir` action: creates a folder at `path` on Nextcloud
- [x] `delete` action: deletes file/folder at `path` on Nextcloud
- [x] Tool registered in `src/agent_tools/__init__.py` (import + entry in TOOLS dict)
- [x] Tool schema added to `src/tool_schemas.py`
- [x] Tool description added to `src/tool_index.py` (BUILTIN_TOOL_DESCRIPTIONS)
- [x] Added to `ALWAYS_AVAILABLE` in `tool_index.py` (alongside `nextcloud_list` and `nextcloud_read_file`)
- [x] Existing `nextcloud_list` and `nextcloud_read_file` tests still pass
- [x] New tests for `nextcloud_write_file` (at minimum: write creates file, mkdir creates folder, delete removes file)
- [x] `python -m py_compile` clean on changed Python files
- [ ] Conventional Commits format

## Implementation plan
1. Add `NextcloudWriteFileTool` class to `src/agent_tools/nextcloud_tools.py`
   - `_execute_write(path, content, account_id, ctx)` — calls `client.put_file(path, content.encode("utf-8"))`
   - `_execute_mkdir(path, account_id, ctx)` — calls `client.mkcol(path)`
   - `_execute_delete(path, account_id, ctx)` — calls `client.delete(path)`
2. Register in `src/agent_tools/__init__.py`: import + add `"nextcloud_write_file": NextcloudWriteFileTool().execute`
3. Add schema to `src/tool_schemas.py`: action enum (`write`/`mkdir`/`delete`), path required, content optional (required for `write`)
4. Add description to `src/tool_index.py` BUILTIN_TOOL_DESCRIPTIONS
5. Add to `ALWAYS_AVAILABLE` frozenset
6. Add tests in `tests/` for write, mkdir, delete actions

## Risks / trade-offs
- LLM could overwrite important files — mitigated by user seeing the action in the chat
- No "append" action initially — write is full overwrite (consistent with `put_file`)
- Binary files not supported via this tool — use the document editor flow for PDFs/images
- Path traversal already blocked by `NextcloudClient._validate_path` (rejects `..`)

## Definition of Done
- [x] `python -m pytest` green (add/extend tests for changed behavior)
- [x] `python -m py_compile` clean on changed Python files
- [x] `node --check` clean on changed JS files (if applicable)
- [x] Path constants from `src/constants.py` used (no hardcoded paths)
- [x] `internal_api_base()` used for loopback URLs (no hardcoded `localhost:7000`)
- [x] No Unicode emoji in UI changes (inline SVG or plain text instead)
- [x] Dark theme preserved; existing CSS variables reused
- [x] No parallel component patterns — extended existing widgets where applicable
- [x] Conventional Commits format ready (`type(scope): summary`)
- [x] Branch from `dev`; PR targets `dev`
- [x] Relevant docs updated
- [x] This spec's `status` advanced and `Changelog` updated

## Changelog
- 2026-07-09 — created (draft) — @spec
- 2026-07-09 — triaged (evidence: sufficient) — @triage
- 2026-07-09 — implemented (branch: dev — 26/26 tests pass) — @implement
- 2026-07-09 — verified (all code criteria met, conventions followed, 10 new tests comprehensive) — @qa
