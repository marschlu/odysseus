---
id: REQ-TEMPLATE
title: "<short, imperative title>"
type: bug            # bug | feature | spike | refactor | chore
status: draft        # draft | triaged | approved | implementing | implemented | verified | done | blocked
priority: normal     # low | normal | high | critical
service: Routes      # Routes | Core | LLM | Agent | Search | Email | MCP | Frontend | Docs | CI/CD
reporter: <you>
created: <date>
---

<!--
  Odysseus request spec. Copy this file to <id>-<slug>.md (e.g. 20260627-add-search-filter.md)
  and fill it in. Keep the YAML frontmatter above as the FIRST thing in the file — the `flow`
  agent parses `status` from it. Status state machine:
  draft -> triaged -> approved -> implementing -> implemented -> verified -> done (+ blocked).
  See the `request-workflow` skill for the full pipeline.
-->

# <Title>

## Summary
One or two sentences: what's wrong (bug) or what's missing (feature).

## Reproduction / Motivation
<!-- bug: numbered repro steps; feature: the user-facing motivation and who benefits -->
1. ...
2. ...
**Actual:** ...
**Expected:** ...

## Expected behavior (codebase-anchored)
<!-- REQUIRED. Describe the behavior the system should exhibit. Cite relevant source files,
     route handlers, service functions, constants, or config values. -->
- <behavior>
- Evidence: `<file>` · function `<name>` · line `<n>`
  (filled in / expanded by the `research` agent when the initial citation is thin)

## Codebase research log
<!-- `research` appends a detailed report here. It documents relevant code locations,
     existing patterns, constants, and test conventions found in the codebase. -->
_(empty until investigated)_

## Acceptance criteria
<!-- Concrete, testable, checkboxed. The `qa` agent verifies each of these. -->
- [ ] ...
- [ ] ...

## Implementation plan
<!-- Filled during/after triage. Which route file, service module, or frontend component
     the change goes in; any new constants needed in src/constants.py; any new DB fields in
     core/database.py; any new tests. -->
1. ...

## Risks / trade-offs
- ...

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
- <date> — created (draft) — @spec
