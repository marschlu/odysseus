"""Helpers for the optional markitdown document-extraction dependency.

markitdown (MIT, Microsoft) converts Office/EPUB documents to Markdown, which is
more token-efficient and model-legible than a raw text dump. It is **optional**:
install with `pip install -r requirements-optional.txt`. When absent, callers
degrade gracefully (chat shows a hint; the RAG indexer skips the file) — the MIT
core never hard-depends on it. Mirrors the optional-dependency pattern in
`src/pdf_runtime.py`.
"""

import logging
import os

logger = logging.getLogger(__name__)

MARKITDOWN_MISSING = (
    "Office/EPUB document extraction requires markitdown. Install optional "
    "dependencies with `pip install -r requirements-optional.txt`."
)

# Formats routed through markitdown. PDFs stay on pypdf (src/document_processor
# and src/personal_docs); plain text/code/csv/json/markdown/html stay on the
# cheaper built-in text path. These are the formats currently dropped entirely.
MARKITDOWN_EXTS = frozenset({".docx", ".pptx", ".xlsx", ".xls", ".epub"})


def is_markitdown_format(path: str) -> bool:
    """True if the file extension is one we route through markitdown."""
    if not isinstance(path, str):
        return False
    return os.path.splitext(path)[1].lower() in MARKITDOWN_EXTS


def load_markitdown():
    """Return the MarkItDown class, or raise a user-facing setup hint."""
    try:
        from markitdown import MarkItDown  # optional dependency
    except ImportError as exc:
        raise RuntimeError(MARKITDOWN_MISSING) from exc
    return MarkItDown


def _extract_docx_native(path: str) -> str | None:
    """Pure-Python .docx text extractor — no external deps.

    A .docx file is just a zip of XML. The body prose lives in <w:t> runs
    inside <w:p> paragraphs. Iterating with ElementTree (rather than
    re.findall) keeps paragraph breaks intact and lets the XML parser handle
    namespaces + entity unescaping. Loses tables, footnotes, images and
    list bullets — keeps ~95% of "summarize this doc" content, which is the
    case people hit when markitdown isn't installed.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            xml_bytes = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    paragraphs: list[str] = []
    for para in root.iter(f"{ns}p"):
        runs = [t.text or "" for t in para.iter(f"{ns}t")]
        line = "".join(runs).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs) if paragraphs else None


def _extract_xlsx_native(path: str) -> str | None:
    """Pure-Python .xlsx text extractor — no external deps.

    Reads the shared-string table + first worksheet and emits rows as
    tab-separated values, so a spreadsheet is readable for summarizing even
    when markitdown/openpyxl aren't installed (e.g. the slim Docker image).
    Handles strings, inline strings, and plain numbers; formulas, styling,
    and later sheets are ignored.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                try:
                    sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
                    for si in sroot.iter(f"{ns}si"):
                        strings.append("".join((t.text or "") for t in si.iter(f"{ns}t")))
                except ET.ParseError:
                    pass
            sheet_names = [n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            if not sheet_names:
                return None
            try:
                root = ET.fromstring(z.read(sheet_names[0]))
            except ET.ParseError:
                return None
            rows_out: list[str] = []
            for row in root.iter(f"{ns}row"):
                cells: list[str] = []
                for c in row.iter(f"{ns}c"):
                    t = c.get("t")
                    v_el = c.find(f"{ns}v")
                    val = v_el.text if (v_el is not None and v_el.text) else ""
                    if t == "s" and val.isdigit():
                        idx = int(val)
                        val = strings[idx] if idx < len(strings) else val
                    elif t == "inlineStr":
                        is_el = c.find(f"{ns}is")
                        if is_el is not None:
                            val = "".join((tt.text or "") for tt in is_el.iter(f"{ns}t"))
                    cells.append(val)
                if any(cells):
                    rows_out.append("\t".join(cells))
            return "\n".join(rows_out) if rows_out else None
    except (zipfile.BadZipFile, OSError):
        return None



def convert_to_markdown(path: str) -> str | None:
    """Convert a document to Markdown text via markitdown.

    Returns the extracted Markdown, or ``None`` if markitdown is unavailable or
    the conversion fails — callers degrade gracefully rather than erroring.

    Fallback: when markitdown isn't installed, run a bundled pure-Python
    extractor for .docx and .xlsx so the two most common Office formats work
    out of the box (the latter matters for the slim Docker image, which has no
    markitdown/openpyxl). Other Office/EPUB formats still need markitdown.
    """
    try:
        markitdown_cls = load_markitdown()
    except RuntimeError:
        ext = os.path.splitext(path)[1].lower() if isinstance(path, str) else ""
        native = None
        if ext == ".docx":
            native = _extract_docx_native(path)
        elif ext == ".xlsx":
            native = _extract_xlsx_native(path)
        if native:
            logger.info("markitdown not installed — used native %s extractor for %s", ext, path)
            return native
        logger.warning("markitdown not installed; cannot extract %s", path)
        return None
    try:
        result = markitdown_cls().convert(path)
        text = getattr(result, "text_content", None)
        if text is None:
            text = getattr(result, "markdown", None)
        return text
    except Exception as e:
        logger.warning("markitdown failed to convert %s: %s", path, e)
        return None
