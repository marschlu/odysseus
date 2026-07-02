---
name: odysseus-frontend
description: Use when working on the Odysseus frontend. Covers the vanilla JS architecture (no React/Vue/Svelte), CSS conventions (single massive style.css, CSS variables, dark theme default, Fira Code, no emoji), JS module structure, and visual style rules from CONTRIBUTING.md.
---

# Odysseus frontend

Vanilla JavaScript, no framework. Single-file CSS (36K+ lines). Dark theme default.

## Entry points

- **`static/index.html`** — main app shell.
- **`static/login.html`** — login page.
- **`static/app.js`** (~4,090 lines) — app initialization and core logic.
- **`static/style.css`** (36,653 lines) — the entire CSS in one file.

## JS modules (`static/js/`)

| File | Lines | Purpose |
|---|---|---|
| `document.js` | ~9,776 | Document/RAG UI |
| `slashCommands.js` | ~6,498 | Slash command palette |
| `app.js` | ~4,090 | Core app logic |
| `cookbook.js` | ~3,200+ | Model cookbook UI |
| `notes.js` | ~2,500+ | Notes module |
| `gallery.js` | ~2,000+ | Image gallery |
| `settings.js` | ~2,000+ | Settings UI |
| … more | | Additional modules |

All vanilla JS — no React, Vue, Svelte, or other framework. DOM manipulation is direct.

## CSS conventions

### Variables (reuse these — never introduce new color/font/spacing literals)
```
--red, --green, --yellow, --blue        # accent colors
--fg, --bg                              # foreground (text) and background
--card, --border                        # card surfaces and borders
--hover, --active                       # interaction states
--radius, --gap, --padding              # spacing tokens
--font-mono                             # usually Fira Code
```

### Rules
- **Reuse existing CSS variables.** Do not introduce new color values, font sizes, or spacing
  units. The existing variables cover the full visual language.
- **Reuse existing button, input, card, and border classes.** Don't invent parallel styling for
  similar widgets. Look at the HTML in `static/index.html` for the canonical class names.
- **No Unicode emoji in UI or code.** Use inline SVG (matching the monochrome icon style already
  in `static/index.html`) or plain text. The project has an established set of SVG icons.
- **Monospaced font (`Fira Code`)** for primary UI text. Don't override with different fonts.
- **Dark theme is the default.** Any light-mode work goes through the existing theme system,
  not hard-coded colors.
- **No parallel components.** If a similar widget already exists in the app, extend it instead
  of writing a new one.

### Style file
A single `static/style.css` (~36K lines). All styles live here — no CSS modules, no CSS-in-JS.
Search with `rg -n "<selector-or-variable>" static/style.css`.

## Visual invariants (qa checks these)
1. No Unicode emoji in any new UI code (use inline SVG).
2. `--red`, `--fg`, `--bg` etc. reused; no new hardcoded color `#...` strings.
3. `Fira Code` is the primary UI font — not overridden.
4. Dark theme is default; light mode goes through the existing `data-theme` system.
5. New widgets extend existing classes — no new parallel component CSS.
6. Screenshots required for any UI change (attach in PR).

## Adding UI (the right way)
1. Find the nearest existing JS module in `static/js/` for the feature area.
2. Look at how similar widgets are built in the HTML (check `static/index.html` for examples).
3. Use the existing `.btn`, `.input`, `.card`, `.modal` CSS classes.
4. Use inline SVG for icons — match the monochrome style used elsewhere.
5. Test in both light and dark theme modes.

## Frontend test conventions
- Node-backed JS tests in `tests/streaming/` (`.mjs` files).
- Run: `node --check static/js/<file>.js` for syntax validation.
- Full JS tests: `python -m pytest tests/ -k "js"` (finds tests with `area_js` marker).
