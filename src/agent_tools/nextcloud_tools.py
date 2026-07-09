"""Agent tools for Nextcloud Files (read/write).

``nextcloud_list`` lists the children of a path on the user's Nextcloud,
``nextcloud_read_file`` reads a text file into the agent's context, and
``nextcloud_write_file`` writes/creates/deletes files on Nextcloud. All
resolve the owner from the tool ``ctx`` and use that owner's first configured
Nextcloud account (or a specific account id when provided). Credentials are
never put in tool output.
"""

import asyncio
import io
import json
import logging
from typing import Optional, Tuple

from src.constants import NEXTCLOUD_MAX_READ_CHARS, NEXTCLOUD_MAX_DOWNLOAD_BYTES
from src.nextcloud_client import NextcloudError

logger = logging.getLogger(__name__)


def _parse_args(content: str) -> dict:
    """Accept either a JSON object or a bare path string as the tool content."""
    text = (content or "").strip()
    if text.startswith("{"):
        try:
            args = json.loads(text)
            if isinstance(args, dict):
                return args
        except (json.JSONDecodeError, TypeError):
            pass
    return {"path": text}


def _resolve_client(ctx: dict, account_id: str = ""):
    """Return (NextcloudClient, label) for the owner's chosen account, or an error string."""
    from routes.nextcloud_routes import _client_for, _find_account, _load_accounts

    owner = ctx.get("owner") or None
    accounts = _load_accounts(owner)
    if not accounts:
        return None, "", "No Nextcloud account is configured. Ask the user to add one in Settings."
    if account_id:
        try:
            account = _find_account(owner, account_id)
        except Exception:
            return None, "", f"No Nextcloud account with id '{account_id}'."
    else:
        account = accounts[0]
    label = account.get("label") or account.get("username") or "Nextcloud"
    try:
        client = _client_for(account)
    except Exception as e:
        return None, "", f"Nextcloud account is misconfigured: {e}"
    return client, label, None


def _human_size(n: Optional[int]) -> str:
    if n is None:
        return "-"
    try:
        f = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{int(f)} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{int(f)} TB"


def _extract_pdf_text(content_bytes: bytes) -> str:
    """Extract text from PDF bytes, trying PyMuPDF (optional) then pypdf (core).

    Returns the extracted text or an empty string if extraction fails.
    """
    # 1. Try PyMuPDF (optional, AGPL — may not be installed)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if text.strip():
            return text
    except Exception:
        pass

    # 2. Try pypdf (core dependency, BSD — always available)
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip():
            return text
    except ImportError:
        logger.warning("pypdf not available — cannot extract PDF text")
    except Exception as e:
        logger.warning(f"pypdf extraction failed: {e}")

    # 3. Fallback: raw UTF-8 decode (for PDFs that are mostly text)
    try:
        raw = content_bytes.decode("utf-8", errors="replace")
        return raw
    except Exception:
        pass

    return ""


class NextcloudListTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        args = _parse_args(content)
        path = str(args.get("path") or "").strip()
        account_id = str(args.get("account") or "").strip()
        client, label, err = _resolve_client(ctx, account_id)
        if err:
            return {"error": f"nextcloud_list: {err}", "exit_code": 1}
        try:
            entries = await asyncio.to_thread(client.list_dir, path)
        except NextcloudError as e:
            return {"error": f"nextcloud_list: {e}", "exit_code": 1}
        except ValueError as e:
            return {"error": f"nextcloud_list: {e}", "exit_code": 1}
        if not entries:
            return {"output": f"nextcloud: {label} — '{path or '/'}' is empty.", "exit_code": 0}
        dirs = sorted([e for e in entries if e.get("is_dir")], key=lambda e: e["name"].lower())
        files = sorted([e for e in entries if not e.get("is_dir")], key=lambda e: e["name"].lower())
        lines = [f"nextcloud: {label} — {path or '/'}"]
        for e in dirs:
            mod = e.get("modified") or ""
            lines.append(f"  {e['name']}/                {mod}")
        for e in files:
            mod = e.get("modified") or ""
            ctype = e.get("content_type") or ""
            lines.append(f"  {e['name']}   {_human_size(e.get('size'))}   {ctype}   {mod}".rstrip())
        return {"output": "\n".join(lines), "exit_code": 0}


class NextcloudReadFileTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        args = _parse_args(content)
        path = str(args.get("path") or "").strip()
        account_id = str(args.get("account") or "").strip()
        if not path:
            return {"error": "nextcloud_read_file: path required", "exit_code": 1}
        client, label, err = _resolve_client(ctx, account_id)
        if err:
            return {"error": f"nextcloud_read_file: {err}", "exit_code": 1}
        name = path.rsplit("/", 1)[-1]
        ext = (name.split(".")[-1] if "." in name else "").lower()
        # PDFs can be large binary files but contain little text — use the
        # generous 50 MB download budget so the file can be downloaded and
        # text extracted. The extracted text is then truncated to the read
        # char limit. Other files use the smaller budget.
        is_pdf_ext = (ext == "pdf")
        budget = NEXTCLOUD_MAX_DOWNLOAD_BYTES if is_pdf_ext else NEXTCLOUD_MAX_READ_CHARS * 4
        try:
            content_bytes, content_type = await asyncio.to_thread(client.get_file, path, budget)
        except NextcloudError as e:
            return {"error": f"nextcloud_read_file: {e}", "exit_code": 1}
        except ValueError as e:
            return {"error": f"nextcloud_read_file: {e}", "exit_code": 1}
        is_pdf_ct = (content_type or "").lower() == "application/pdf"
        is_pdf = is_pdf_ext or is_pdf_ct
        if is_pdf:
            text = _extract_pdf_text(content_bytes)
            if not text.strip():
                return {"error": f"nextcloud_read_file: could not extract text from PDF {name}", "exit_code": 1}
            if len(text) > NEXTCLOUD_MAX_READ_CHARS:
                text = text[:NEXTCLOUD_MAX_READ_CHARS] + f"\n... [truncated at {NEXTCLOUD_MAX_READ_CHARS} chars]"
            header = f"[nextcloud:{label}] {path}"
            return {"output": f"{header}\n{text}", "exit_code": 0}
        if ext in {"docx", "pptx", "xlsx", "xls", "epub", "odt", "ods", "odp"}:
            return {"error": f"nextcloud_read_file: cannot read binary file {name} — file viewer available in the Nextcloud explorer.", "exit_code": 1}
        text = content_bytes.decode("utf-8", errors="replace")
        if not text.strip():
            return {"error": f"nextcloud_read_file: could not extract text from {name}", "exit_code": 1}
        if len(text) > NEXTCLOUD_MAX_READ_CHARS:
            text = text[:NEXTCLOUD_MAX_READ_CHARS] + f"\n... [truncated at {NEXTCLOUD_MAX_READ_CHARS} chars]"
        header = f"[nextcloud:{label}] {path}"
        return {"output": f"{header}\n{text}", "exit_code": 0}


class NextcloudWriteFileTool:
    """Write, create folders, or delete files on Nextcloud via WebDAV."""

    async def execute(self, content: str, ctx: dict) -> dict:
        args = _parse_args(content)
        action = str(args.get("action") or "").strip().lower()
        path = str(args.get("path") or "").strip()
        account_id = str(args.get("account") or "").strip()
        text_content = args.get("content")

        if not action:
            return {"error": "nextcloud_write_file: action required (write, mkdir, delete)", "exit_code": 1}
        if action not in ("write", "mkdir", "delete"):
            return {"error": f"nextcloud_write_file: unknown action '{action}' — use write, mkdir, or delete", "exit_code": 1}
        if not path:
            return {"error": "nextcloud_write_file: path required", "exit_code": 1}

        client, label, err = _resolve_client(ctx, account_id)
        if err:
            return {"error": f"nextcloud_write_file: {err}", "exit_code": 1}

        try:
            if action == "write":
                if text_content is None:
                    return {"error": "nextcloud_write_file: content required for write action", "exit_code": 1}
                await asyncio.to_thread(client.put_file, path, str(text_content).encode("utf-8"))
                return {"output": f"nextcloud: {label} — wrote {len(str(text_content))} chars to {path}", "exit_code": 0}

            if action == "mkdir":
                await asyncio.to_thread(client.mkcol, path)
                return {"output": f"nextcloud: {label} — created folder {path}", "exit_code": 0}

            # action == "delete"
            await asyncio.to_thread(client.delete, path)
            return {"output": f"nextcloud: {label} — deleted {path}", "exit_code": 0}

        except NextcloudError as e:
            return {"error": f"nextcloud_write_file: {e}", "exit_code": 1}
        except ValueError as e:
            return {"error": f"nextcloud_write_file: {e}", "exit_code": 1}
