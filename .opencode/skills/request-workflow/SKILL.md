---
name: request-workflow
description: "The Odysseus request/spec pipeline state machine and conventions. Defines the spec status values, which agent runs at each stage, the two human approval gates, the spec filename/id rules, and the Definition-of-Done. Loaded by the `flow` orchestrator agent. Specs live in .opencode/requests/."
---

# Odysseus request workflow

A structured pipeline for turning bug reports / feature requests into verified Odysseus code.
The **spec file** (`.opencode/requests/<id>-<slug>.md`) is the single source of truth, and its YAML
`status` field **is** the workflow state — the `flow` agent dispatches on it.

**Guiding principle:** the spec drives every stage. No work happens without a spec; no code is
written without your approval; nothing is merged without your sign-off.

## Agents in the pipeline
| Agent       | Mode        | Role                                                       |
|-------------|-------------|------------------------------------------------------------|
| `flow`      | primary     | Orchestrator: reads `status`, dispatches the next stage, enforces the two human gates. |
| `spec`      | subagent    | Intake: raw report -> `draft` spec; classifies + initial codebase citation. |
| `triage`    | subagent    | Quality gate: completeness/dedup/priority; may call `research`; -> `triaged`. |
| `research`  | subagent (hidden) | Deep codebase investigation; returns a research report. Called by triage. |
| `implement` | all         | Coder: branch + code + `pytest` + syntax checks; -> `implemented`. Loads `odysseus-*` skills. |
| `qa`        | subagent    | Verifier: criteria + conventions + checks + fidelity; -> `verified` or back. |

## State machine (`status` field)
```
                       @spec                 @triage (may call @research)
(new report) ───────────────▶ draft ─────────────────────▶ triaged
                                                            │
                                               [HUMAN GATE 1: approve spec]
                                                            ▼
                                                         approved
                                                            │ @implement
                                                            ▼
                                                      implementing
                                                            │ (checks green)
                                                            ▼
                                                      implemented
                                                            │ @qa
                                                            ▼
                                                       verifying ──┐
                                                            │       │ fails -> back to implementing
                                               [criteria met]       │   (with QA findings notes)
                                                            ▼       │
                                                        verified ◀──┘
                                                            │
                                               [HUMAN GATE 2: approve commit/merge]
                                                            ▼
                                                           done
```
`blocked` may be set at any stage (triage can't get evidence, implement hits a spec gap, etc.).
Flow surfaces the blocker and stops.

## Dispatch table (what `flow` calls for each status)
| status        | action                                   |
|---------------|------------------------------------------|
| (no spec)     | `spec` — create from raw report          |
| `draft`       | `triage`                                 |
| `triaged`     | STOP — human gate 1                      |
| `approved`    | `implement`                              |
| `implementing`/`verifying` | STOP — subagent in progress   |
| `implemented` | `qa`                                     |
| `verified`    | STOP — human gate 2                      |
| `done`        | STOP — summarize                         |
| `blocked`     | STOP — surface blocker                   |

## Spec conventions
- **Location**: `/home/ryu/Documents/odysseus/.opencode/requests/`
- **Filename**: `YYYYMMDD-<slug>.md` (slug = 1-3 lowercase hyphenated words).
- **`id`** = filename stem. Glob the folder first to avoid collisions.
- **Template**: `.opencode/requests/_TEMPLATE.md` — reproduce its frontmatter keys exactly (flow
  parses `status`).
- Frontmatter `status` ∈ {`draft`, `triaged`, `approved`, `implementing`, `implemented`,
  `verified`, `done`, `blocked`}.

## Definition of Done (in every spec; `qa` verifies)
- `python -m pytest` green (add/extend tests for changed behavior).
- `python -m py_compile` clean on changed Python files.
- `node --check` clean on changed JS files (if applicable).
- Path constants from `src/constants.py` used (no hardcoded paths).
- `internal_api_base()` used for loopback URLs (no hardcoded `localhost:7000`).
- No Unicode emoji in UI changes (inline SVG or plain text instead).
- Dark theme preserved; existing CSS variables reused.
- No parallel component patterns — extended existing widgets where applicable.
- Conventional Commits format ready (`type(scope): summary`).
- Branch from `dev`; PR targets `dev`.
- Relevant docs updated.
- Spec `status` advanced; Changelog updated.

## How a session looks
1. User Tabs to **`flow`** and pastes a raw report (or refs an existing spec id).
2. `flow` runs `spec -> triage (-> research if needed)`, then pauses at **gate 1** showing the
   completed spec for approval.
3. User approves -> `flow` runs `implement -> qa`, reports the verdict.
4. User approves at **gate 2** -> commit/merge -> `done`.

## Notes
- Everything (specs, agents, this skill) lives at the workspace `.opencode/` — **not** in the
  shared Odysseus repo. It's a personal you+agent workflow.
- `flow` never writes application code or runs checks; subagents do the work, flow only dispatches.
- The two human gates are mandatory — no autonomous path from report to merge.
