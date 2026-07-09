---
id: 20260704-nextcloud-llm-pdf-reading
title: "Enable LLM PDF reading from Nextcloud via nextcloud_read_file"
type: feature
status: implemented
priority: normal
service: Agent
reporter: @spec
created: 2026-07-05
---

# Enable LLM PDF reading from Nextcloud via nextcloud_read_file

## Summary
The `nextcloud_read_file` agent tool rejects PDFs as unsupported binary files. The LLM cannot extract information from PDFs stored on Nextcloud. This feature teaches the tool to download a PDF, extract text via `pypdf` (core dependency, always available) with an optional PyMuPDF fast-path, and return the extracted text to the LLM — while keeping existing rejection for other binary formats (docx, xlsx, epub, etc.).

## Reproduction / Motivation
Who benefits: any user whose Nextcloud holds PDF reports, papers, scanned documents, or forms and wants the LLM to read/summarize/search them without manually downloading and uploading.

1. Configure a Nextcloud account in Settings.
2. Upload a PDF (e.g. `reports/2024-summary.pdf`) to Nextcloud.
3. In a chat, ask the LLM: "read and summarize my Nextcloud file reports/2024-summary.pdf".
4. **Actual:** tool returns `"cannot read binary file reports/2024-summary.pdf — file viewer available in the Nextcloud explorer."`
5. **Expected:** tool returns the extracted text (page-by-page or concatenated), truncated at `NEXTCLOUD_MAX_READ_CHARS` if needed.

## Expected behavior (codebase-anchored)
- When `nextcloud_read_file` is called on a file whose extension is `.pdf` (case-insensitive), the tool downloads the raw bytes via `client.get_file(path, budget)` and extracts human-readable text rather than returning the existing binary-rejection error.
- Text extraction uses `pypdf.PdfReader` (core dependency, always available per `requirements.txt` line 10). If PyMuPDF (`fitz`) is installed as an optional dependency, it may be used as a preferred fast-path, but the tool must degrade gracefully to `pypdf` and then to a raw-byte decode fallback.
  - Evidence: `src/pdf_runtime.py` · function `load_pymupdf_for_pdf_viewer()` · lines 9–15 — established pattern for optional PyMuPDF import.
  - Evidence: `src/personal_docs.py` · function `extract_pdf_text()` · lines 14–26 — existing `pypdf.PdfReader` extraction pattern (file-path-based; an in-memory `BytesIO` variant is needed here).
- The download budget respects existing constants:
  - Evidence: `src/constants.py` · `NEXTCLOUD_MAX_DOWNLOAD_BYTES` (50 MB default) · line 96 — download ceiling.
  - Evidence: `src/agent_tools/nextcloud_tools.py` · line 111 — `budget = NEXTCLOUD_MAX_READ_CHARS * 4` for byte budget; the PDF download should use the same or a reasonable fraction of `NEXTCLOUD_MAX_DOWNLOAD_BYTES`.
- Extracted text is truncated to `NEXTCLOUD_MAX_READ_CHARS` (same as current text path):
  - Evidence: `src/agent_tools/nextcloud_tools.py` · lines 124–125 — existing truncation logic.
- The tool continues to reject all other binary formats (docx, pptx, xlsx, xls, epub, odt, ods, odp) with the existing error message:
  - Evidence: `src/agent_tools/nextcloud_tools.py` · line 119 — current extension blocklist.
- Content-type detection: if the server returns `application/pdf` but the filename lacks `.pdf`, the tool should still attempt PDF extraction based on content-type rather than rejecting as binary.
- The `nextcloud_client.get_file()` signature already returns `(content_bytes, content_type)`:
  - Evidence: `src/nextcloud_client.py` · function `get_file()` · line 286 — returns `Tuple[bytes, Optional[str]]`.

## Codebase research log
- **2026-07-05 — triage verification** — all citations confirmed against current codebase:
  - `src/agent_tools/nextcloud_tools.py` L111,119,124-125: budget (`NEXTCLOUD_MAX_READ_CHARS * 4`), blocklist (pdf in blocked set), truncation logic.
  - `src/constants.py` L96: `NEXTCLOUD_MAX_DOWNLOAD_BYTES = 50_000_000` (env-overridable).
  - `src/nextcloud_client.py` L286: `get_file(path, max_bytes) -> Tuple[bytes, Optional[str]]`.
  - `src/pdf_runtime.py` L9-15: existing optional PyMuPDF (`fitz`) import pattern via `load_pymupdf_for_pdf_viewer()`.
  - `src/personal_docs.py` L14-26: existing `extract_pdf_text()` using `pypdf.PdfReader` (file-path-based; in-memory `BytesIO` variant needed).
  - `src/tool_index.py` L79: description says "binary files are not supported."
  - `src/tool_schemas.py` L173: description says "binary files may not be useful."
  No `TODO(research)` gaps remain. Evidence is sufficient — no separate research pass required.

## Acceptance criteria
- [x] Calling `nextcloud_read_file` on a `.pdf` file returns extracted text in `output` with `exit_code: 0`.
- [x] PDF text extraction works when only `pypdf` is installed (core dependency — no PyMuPDF required).
- [x] When PyMuPDF is available, it is used; when absent, `pypdf` handles extraction; when `pypdf` fails, a raw byte decode fallback is attempted with a warning log.
- [x] Non-PDF binary formats (docx, xlsx, pptx, epub, odt, ods, odp) continue to return `exit_code: 1` with the existing "cannot read binary file" error.
- [x] Extracted text respects `NEXTCLOUD_MAX_READ_CHARS` truncation (consistent with plain-text file behavior).
- [x] Download respects `NEXTCLOUD_MAX_DOWNLOAD_BYTES` ceiling (no multi-GB PDF streaming into memory).
- [x] Files whose content-type is `application/pdf` are treated as PDF even if the extension is missing or non-standard.
- [x] A `pypdf` import failure (should not happen since it is a core dependency) is caught gracefully and returns a clear error instead of a traceback.
- [x] Existing test `test_read_file_tool_rejects_binary` is updated to expect PDF extraction (or a new test replaces it for PDF, and the old test is scoped to a non-PDF binary).
- [x] `python -m pytest` green for all affected/changed tests.

## Implementation plan
1. **Modify `src/agent_tools/nextcloud_tools.py`** — `NextcloudReadFileTool.execute()`:
   - After the `ext` check on line 119, split PDF out of the blocklist.
   - Add a `_extract_pdf_text(content_bytes: bytes) -> str` helper that tries:
     a. PyMuPDF (`fitz.open(stream=..., filetype="pdf")`) — optional fast-path.
     b. `pypdf.PdfReader(BytesIO(content_bytes))` — always-available fallback.
     c. Raw `content_bytes.decode("utf-8", errors="replace")` — last resort.
   - Call the helper, truncate to `NEXTCLOUD_MAX_READ_CHARS`, return as output.
   - Also check `content_type == "application/pdf"` when ext is not `.pdf`.
2. **Update `src/tool_index.py`** line 79 — description: remove "binary files are not supported" and note PDF support.
3. **Update `src/tool_schemas.py`** line 173 — description: same wording update.
4. **Update/add tests in `tests/test_nextcloud_files_owner_scope.py`**:
   - Update `test_read_file_tool_rejects_binary` to use a non-PDF binary (e.g. `.docx`).
   - Add `test_read_file_tool_extracts_pdf_text` — mock `client.get_file` to return real-looking PDF bytes, assert extracted text.
   - Add `test_read_file_tool_extracts_pdf_by_content_type` — file named `report` but content-type `application/pdf`.
   - Add `test_read_file_tool_pdf_no_pypdf_fallback` — simulate `pypdf` import failure, assert graceful error.

## Risks / trade-offs
- **PyMuPDF is AGPL-3.0** — must remain optional; the tool's core PDF path must work with `pypdf` alone (BSD-licensed, already in `requirements.txt`). The PyMuPDF fast-path is purely a quality improvement.
- **In-memory extraction** — PDF bytes are held in RAM. The existing `NEXTCLOUD_MAX_DOWNLOAD_BYTES` (50 MB) and the `NEXTCLOUD_MAX_READ_CHARS * 4` byte budget mitigate this. Large PDFs with embedded images may still be heavy; `pypdf` only reads text streams and is efficient.
- **Scanned/image-only PDFs** — `pypdf` and PyMuPDF text extraction return empty strings for pure-image PDFs. The raw-byte-decode fallback will also produce garbage. This is acceptable for now; a future enhancement could route image-heavy PDF pages through a vision model (as `document_processor._process_pdf` already does at line 112).
- **Tool description drift** — the LLM prompt via `tool_index.py` and `tool_schemas.py` says "binary files are not supported." If not updated, the LLM may still avoid calling the tool on PDFs even after the code supports it.

## Definition of Done
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
- 2026-07-05 — implemented on `feat/nextcloud-pdf-reading` — @implement
