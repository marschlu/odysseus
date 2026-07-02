---
name: odysseus-testing
description: Use when writing or running tests for Odysseus. Covers pytest configuration, taxonomy markers, fast lane, conftest stubs, the bombadil spec testing tool, run_focus and run_order_report helpers, JS test conventions, and TESTING_STANDARD.md (behavioral-first, deterministic, isolated).
---

# Odysseus testing

pytest + pytest-asyncio is the sole testing framework. ~580+ test files (~54,800 lines of tests).

## Configuration (`pyproject.toml`)
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

## Taxonomy markers

Tests are automatically classified by `tests/_taxonomy.py` using filename token matching.
Markers are declared in `pyproject.toml`:

| Marker | What it covers |
|---|---|
| `area_security` | Auth, owner-scope, SSRF, XSS, confinement, redaction |
| `area_routes` | HTTP route / API behavior |
| `area_services` | Service-layer: llm, cookbook, email, calendar, etc. |
| `area_cli` | CLI / script behavior |
| `area_js` | JavaScript / Node-backed tests |
| `area_helpers` | Test helper self-tests |
| `area_unit` | Pure parser / utility tests |
| `area_uncategorized` | Fallback — not yet classified |

Dynamic `sub_<filename-token>` markers are registered before collection by `pytest_configure`
in `tests/conftest.py`.

## Fast lane

The `--fast` flag runs `not slow` marked tests. Mark a test as `slow` only with duration
evidence:
```bash
python -m pytest --fast                              # fast lane
python -m pytest --durations=20                      # find slow tests
python -m pytest tests/path/to/test.py --fast        # focused fast
```

## Focused test runner

`tests/run_focus.py` provides area/sub-area filtering:
```bash
python tests/run_focus.py --area security --sub-area owner_scope --fast
python tests/run_focus.py --area routes
```

## Order-sensitivity detection

`tests/run_order_report.py` shuffles by seeded RNG to find order-sensitive tests:
```bash
python tests/run_order_report.py
```

## Conftest stubs (`tests/conftest.py`)

Stubs heavy dependencies (SQLAlchemy, FastAPI, etc.) at import time to keep tests fast.
If your test needs the real module, import it within the test function, not at module level.

## Test helpers (`tests/helpers/`)

- `import_state` — manage module import state for clean test isolation.
- SQLite temp DB — for testing DB-backed code without Docker.
- CLI loader — load CLI scripts in-process.
- DB stubs — mock DB calls without real connections.

## Bombadil (structured/contract testing)

The npm package `@antithesishq/bombadil` is used via `tests/bombadil-spec.ts` for structured
testing. Run it separately:
```bash
npx bombadil tests/bombadil-spec.ts
```

## JS tests

Node-backed JS tests live in `tests/streaming/` (`.mjs` files). Run syntax checks:
```bash
node --check static/js/<file>.js          # syntax check
python -m pytest tests/ -k "js"           # full JS test suite
node tests/streaming/<test>.mjs           # individual Node test
```

## Test commands (run from project root)

```bash
python -m pytest                                            # full suite
python -m pytest -x                                         # stop on first failure
python -m pytest --fast                                     # fast lane (skip slow)
python -m pytest tests/test_somefile.py                     # single file
python -m pytest tests/ -k "test_name"                      # keyword filter
python -m pytest --co --timeout=30                          # show options + timeout
python -m py_compile app.py routes/*.py src/*.py            # Python syntax check
node --check static/js/<file>.js                             # JS syntax check
```

## Test-writing conventions (from `TESTING_STANDARD.md`)

- **Behavioral-first**: test what the system does, not how it's implemented.
- **Deterministic**: no reliance on timing, random state, or external services.
- **Isolated**: each test sets up and tears down its own state. No shared fixtures that mutate.
- **Order-independent**: tests must pass regardless of execution order.
- **Taxonomy markers**: add relevant `area_*` markers so focused runs work.
- **For route tests**: test through the FastAPI test client, not by calling functions directly.
- **For service tests**: stub external calls (HTTP, subprocess, DB) within the test body.
- **For DB tests**: use `tests/helpers/` SQLite temp DB or mock the DB layer.
- **No live external services**: no real API calls, no Docker dependency in tests.

## Common gotchas
- Slow tests must have duration evidence before marking `slow`. Run `--durations=20` to find them.
- Don't use `time.sleep()` in tests — use `asyncio.sleep(0)` for yield points or mock the timer.
- `conftest.py` stubs are aggressive — if a test is mysteriously failing, check whether a needed
  module is being stubbed. Import the real module inside the test if needed.
- Taxonomy matching is filename-token-based — name test files to match the area they cover.
