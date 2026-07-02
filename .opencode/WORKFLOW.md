# Working with the Request Workflow (agents / flow)

A practical guide to the Odysseus bug/feature pipeline. This is the *how-to*; the
`request-workflow` skill holds the machine-precise state machine, and `odysseus-*` hold
the project knowledge (backend, frontend, testing).

Everything here lives at the workspace `.opencode/` — it is **not** part of the shared GitHub
Odysseus repo. It's a personal you + agent workflow.

---

## TL;DR — the 30-second version

1. **Tab** to the **`flow`** agent.
2. Paste a raw bug report or feature idea (or name an existing spec, e.g. `20260627-add-search-filter`).
3. `flow` drafts + triages it automatically, then **pauses** and shows you a completed spec.
4. Say **"approve"** → it implements + verifies automatically, then **pauses** again.
5. Say **"approve"** → commit/merge → **done**.

You only ever talk to `flow`. It dispatches the specialist agents behind the scenes and stops at
two mandatory approval points. You never have to remember which agent does what.

---

## The agents (what each one does)

You don't invoke these directly in the normal flow — `flow` does. But you *can* drive any of them
yourself (see "Advanced / manual control" below).

| Agent       | Mode          | Job                                                        | Can edit code? | Can build/test? |
|-------------|---------------|------------------------------------------------------------|----------------|-----------------|
| `flow`      | **primary**   | Orchestrator. Reads the spec's `status`, calls the next agent, enforces the 2 human gates. | No  | No  |
| `spec`      | subagent      | Turns your raw report into a structured spec file. Classifies it, drafts acceptance criteria, finds an initial codebase citation. | No  | No  |
| `triage`    | subagent      | Quality gate: complete? duplicate? right priority? Enough codebase evidence? Calls `research` if evidence is thin. | No  | No  |
| `research`  | subagent (hidden) | Deep investigation of the codebase. Returns a structured research report. | No  | No  |
| `implement` | all (also Tab-drivable) | The coder. Branches, writes code, runs `pytest` + syntax checks. | Yes | Yes |
| `qa`        | subagent      | Verifier. Checks the diff against the spec, re-checks project conventions, runs `pytest`+syntax checks, confirms invariants. | No (spec only) | Yes |

The principle: **read-only agents investigate, `implement` is the only one that writes application
code, `qa` is independent and can bounce work back.** No agent merges or pushes without your say-so.

---

## The lifecycle of a request

Every request is one markdown file in `.opencode/requests/` (e.g.
`20260627-add-search-filter.md`). Its YAML `status` field **is** the workflow state:

```
(new report) ─@spec─▶ draft ─@triage─▶ triaged
                                       │
                         [GATE 1: you approve the spec]
                                       ▼
                                   approved ─@implement─▶ implementing ─▶ implemented
                                                                         │
                                                                   @qa verifies
                                                                         ▼
                            done ◀─[GATE 2: you approve merge]─ verified ◀─ (or bounce back to implementing)
```

| `status`        | Meaning                                  | Who acts next        |
|-----------------|------------------------------------------|----------------------|
| `draft`         | spec just authored                       | `triage` (auto)      |
| `triaged`       | ready for your review                    | **you** (Gate 1)     |
| `approved`      | you approved; code it                    | `implement` (auto)   |
| `implementing`  | being coded                              | (wait)               |
| `implemented`   | code done, needs checking                | `qa` (auto)          |
| `verifying`     | being checked                            | (wait)               |
| `verified`      | passed QA                                | **you** (Gate 2)     |
| `done`          | committed/merged                         | —                    |
| `blocked`       | stuck (missing evidence, spec gap, …)    | **you** (unblock)    |

---

## Skills: the knowledge layer

Agents are the *who*; **skills** are the *what they know*. Each agent loads the skills it needs via
the `skill` tool. You don't manage this — it's wired into each agent's prompt — but knowing the map
helps you trust the output and know where evidence comes from.

| Skill                | What it holds                                    | Loaded by                  |
|----------------------|--------------------------------------------------|----------------------------|
| `request-workflow`   | The state machine, dispatch table, DoD.          | `flow` (every session)     |
| `odysseus-backend`   | Project layout, FastAPI, SQLAlchemy, constants, security invariants, Docker. | `spec`, `research`, `implement`, `qa` |
| `odysseus-frontend`  | Vanilla JS architecture, CSS variables, no-emoji rule, dark theme, Fira Code. | `spec`, `research`, `implement`, `qa` |
| `odysseus-testing`   | pytest config, taxonomy, fast lane, helpers, bombadil, TESTING_STANDARD.md. | `spec`, `research`, `implement`, `qa` |

The first (`request-workflow`) is the pipeline's own knowledge; the last three are the project
skills that make this an *Odysseus* workflow.

---

## Starting a session

OpenCode discovers the agents/skills by walking up from your working directory, so run it from
the workspace root (`/home/ryu/Documents/odysseus`) — that's where `.opencode/` lives.

1. Launch OpenCode from `/home/ryu/Documents/odysseus`.
2. Press **Tab** to cycle primary agents until you see **`flow`**.
3. Type your request and hit enter.

That's it. `flow` loads the `request-workflow` skill, figures out the stage, and dispatches.

---

## Worked example A — a bug report

You:
```
@flow When I click "New Document" in the notes panel, the modal opens but the
save button is greyed out even when text is entered. Works in Firefox, broken in Chrome.
```

What happens:
- `flow` → `spec`: creates `20260627-notes-save-button-disabled.md` (`status: draft`),
  classifies `type: bug`, `service: Frontend`, drafts repro + acceptance criteria, finds an initial
  citation for the notes JS module.
- `flow` → `triage`: checks completeness, calls `research` to map the save-button enable/disable
  logic in `static/js/notes.js` and any related CSS, fills the **Codebase research log**, sets
  `status: triaged`.
- `flow` **stops** and shows you the spec.

You:
```
approve
```
- `flow` → `implement`: branches off `dev`, codes the fix (fixes the Chrome-specific DOM event
  handling), runs `pytest` + `node --check static/js/notes.js`, ticks criteria, sets
  `status: implemented`.
- `flow` → `qa`: verifies the diff, confirms CSS variable reuse, no emoji, checks `node --check`
  passes, runs `pytest`, sets `status: verified`.
- `flow` **stops** and reports the verdict.

You:
```
approve, commit it
```
- The change is committed on the branch; spec → `done`.

---

## Worked example B — a feature request

You:
```
@flow Add a dark-mode toggle to the settings page that switches between the
existing dark and light themes without a page reload.
```

- `spec` classifies `type: feature`, `service: Frontend` (+ Routes), drafts motivation + criteria.
- `triage` calls `research` to find the existing theme system in `static/js/settings.js` and
  the CSS `data-theme` attribute pattern.
- You review the spec at Gate 1, maybe tweak criteria, then `approve`.
- `implement`/`qa` proceed as above. A feature this size may bounce `implemented ↔ verifying` a
  couple of times — `qa` writes concrete `## QA findings (round N)` notes and `flow` redispatches.

---

## The two human gates (don't skip them)

- **Gate 1 — approve the spec** (`triaged` → `approved`): your chance to fix scope, criteria, or
  priority *before* any code is written. Cheapest place to change direction.
- **Gate 2 — approve the merge** (`verified` → `done`): your final sign-off. Nothing is committed
  or pushed automatically.

If you dislike something at either gate, just say so — e.g. *"reject, the criteria are wrong,
add …"* and `flow` will route it back to the right stage.

---

## Advanced / manual control

You're not forced to go through `flow`. You can drive stages directly:

- **`@spec <report>`** — author a spec without the orchestrator.
- **`@triage 20260627-add-search-filter`** — re-triage an existing spec.
- **`@qa 20260627-add-search-filter`** — re-verify after you hand-edit code.
- **Tab → `implement`** then *"implement spec 20260627-add-search-filter"* — drive the coder
  yourself, useful when you want to pair on a tricky change.

Manual edits to a spec file are fine — just keep the frontmatter `status` honest so `flow` knows
where things stand. If you set `status: blocked`, tell `flow` why in the spec body.

You can also **resume** an in-flight request any time:
```
@flow continue 20260627-add-search-filter
```
`flow` reads the `status` and picks up at the right stage.

---

## Where everything lives

```
.opencode/
├── WORKFLOW.md                       ← you are here
├── agents/
│   ├── flow.md        spec.md        triage.md
│   ├── research.md    implement.md   qa.md
├── requests/
│   ├── _TEMPLATE.md                  ← the spec template (copy this)
│   └── 20260627-*.md                 ← your specs (one file per request)
└── skills/
    ├── request-workflow/SKILL.md     ← state machine (loaded by flow)
    ├── odysseus-backend/SKILL.md     ← Python/FastAPI project map (loaded by spec/research/implement/qa)
    ├── odysseus-frontend/SKILL.md    ← JS/CSS style guide (loaded by spec/research/implement/qa)
    └── odysseus-testing/SKILL.md     ← pytest conventions (loaded by spec/research/implement/qa)
```

Spec filename rule: `YYYYMMDD-<slug>.md`, slug = 1–3 lowercase hyphenated words. The `id`
frontmatter field equals the filename stem.

---

## Conventions & gotchas

- **One file, one request.** If a report bundles two things, `spec` will tell `flow` to split them.
- **The spec is the source of truth.** `flow` and the agents read it; don't keep parallel notes in
  chat. Edit the spec, not the conversation.
- **Path constants from `src/constants.py`** — never hardcode writable paths or `localhost:7000`.
- **No Unicode emoji.** Use inline SVG icons or plain text. `qa` always checks for this.
- **Dark theme is default.** Any light-mode work must go through the existing `data-theme` system.
- **Reuse CSS variables.** Don't introduce new color values, font sizes, or spacing units.
- **Branch from `dev`, PR to `dev`.** Never branch from or commit to `main`.
- **Conventional Commits:** `type(scope): summary` — used at commit time.
- **`research` never fabricates evidence.** If it can't find a code reference, it says so. A
  `TODO(research)` or `evidence: partial` is correct for sparse areas.
- **Screenshots are required for UI changes** — `qa` may note if they're missing.

## Tuning the pipeline

The whole flow is plain markdown + frontmatter — edit it to fit how you work:

- **Rename / repurpose a stage:** edit the matching `agents/*.md`. The dispatch logic lives in
  `flow.md` (the dispatch table) and the `request-workflow` skill.
- **Add a stage** (e.g. a `security` review before `qa`): add `agents/security.md`, add it to
  `flow.md`'s `permission.task` allow-list and the state machine, and extend the skill.
- **Change the human gates:** they're just `STOP` rows in `flow.md`'s dispatch table — remove one
  to automate further (do this deliberately; the gates exist to keep you in control of mutations).
- **Tighten/loosen permissions:** each agent's `permission` block controls tools, bash commands,
  and which subagents it may call.

After editing agents/skills, start a **new session** so OpenCode re-discovers them.
