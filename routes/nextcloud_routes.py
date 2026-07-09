"""Nextcloud Files routes — WebDAV file explorer with open-in-asset support.

Per-user account storage mirrors CalDAV: credentials live in the user's prefs
(``nextcloud_accounts`` key via ``routes/prefs_routes.py``), with the app
password encrypted at rest through ``src.secret_storage`` and never returned by
any endpoint. Listings, file reads, and connection testing go through
:class:`NextcloudClient`. The ``open-in-asset`` endpoint routes text/PDF/image
files into the editor, PDF viewer, or Gallery.
"""

import asyncio
import hashlib
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from src.auth_helpers import get_current_user, require_user
from src.constants import GENERATED_IMAGES_DIR, NEXTCLOUD_MAX_DOWNLOAD_BYTES
from src.nextcloud_client import NextcloudClient, NextcloudError, validate_nextcloud_url

logger = logging.getLogger(__name__)

PREFS_KEY = "nextcloud_accounts"


async def _require_owner(request: Request) -> Optional[str]:
    """Gate the route on auth, then resolve the prefs owner.

    ``require_user`` raises 401 when auth is on and no one is logged in. For
    prefs we pass the raw current user (``None`` in single-user mode) so
    ``_load_for_user`` reads the shared first-user slot, exactly like CalDAV.
    """
    require_user(request)
    return get_current_user(request)


def _load_accounts(owner: Optional[str]) -> List[dict]:
    from routes.prefs_routes import _load_for_user

    prefs = _load_for_user(owner) or {}
    return list(prefs.get(PREFS_KEY) or [])


def _save_accounts(owner: Optional[str], accounts: List[dict]) -> None:
    from routes.prefs_routes import _load_for_user, _save_for_user

    prefs = _load_for_user(owner) or {}
    prefs[PREFS_KEY] = accounts
    _save_for_user(owner, prefs)


def _redact(account: dict) -> dict:
    """Public view of an account — never includes the app password."""
    return {
        "id": account.get("id"),
        "label": account.get("label", "") or "",
        "base_url": account.get("base_url", "") or "",
        "username": account.get("username", "") or "",
        "configured": bool(account.get("password")),
    }


def _find_account(owner: Optional[str], account_id: str) -> dict:
    for acc in _load_accounts(owner):
        if acc.get("id") == account_id:
            return acc
    raise HTTPException(404, "Nextcloud account not found")


def _client_for(account: dict) -> NextcloudClient:
    # secret_storage is imported lazily: importing it at module top creates a
    # circular import at app startup (matches contacts_routes / caldav_sync).
    from src.secret_storage import decrypt

    try:
        return NextcloudClient(
            account.get("base_url", ""),
            account.get("username", ""),
            decrypt(account.get("password") or ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


def _map_nextcloud_error(e: NextcloudError) -> HTTPException:
    status = e.status or 502
    if status in (401, 403):
        return HTTPException(status, str(e))
    if status == 404:
        return HTTPException(404, str(e))
    if status == 413:
        return HTTPException(413, str(e))
    return HTTPException(502, str(e))


async def _writeback_nextcloud_doc(doc_id: str, content: str, owner: str) -> None:
    """Fire-and-forget: push a document save back to its Nextcloud source.

    This runs asynchronously after a document save so the HTTP response is
    never blocked.  On success it sets ``nextcloud_sync_status = "synced"``;
    on failure it stores the error in ``nextcloud_sync_error``.  Every
    exception is caught — writeback is best-effort.
    """
    from core.database import SessionLocal as _SL, Document as _Doc

    db = _SL()
    try:
        doc = db.query(_Doc).filter(_Doc.id == doc_id).first()
        if not doc or not doc.source_nextcloud_account or not doc.source_nextcloud_path:
            return

        # Look up the Nextcloud account credentials
        try:
            account = _find_account(owner, doc.source_nextcloud_account)
            client = _client_for(account)
        except HTTPException:
            # Account gone or misconfigured — flag but don't crash.
            doc.nextcloud_sync_status = "error"
            doc.nextcloud_sync_error = "Nextcloud account not found"
            db.commit()
            return
        except Exception as e:
            doc.nextcloud_sync_status = "error"
            doc.nextcloud_sync_error = str(e)[:500]
            db.commit()
            return

        # Upload via WebDAV PUT
        await asyncio.to_thread(client.put_file, doc.source_nextcloud_path, content.encode("utf-8"))

        # Success: update sync status
        doc.nextcloud_sync_status = "synced"
        doc.nextcloud_synced_at = datetime.now(timezone.utc)
        doc.nextcloud_sync_error = None
        db.commit()
        logger.info("Nextcloud writeback OK: %s/%s", doc.source_nextcloud_account, doc.source_nextcloud_path)
    except Exception as e:
        logger.error("Nextcloud writeback failed: %s", e)
        try:
            db.rollback()
            doc2 = db.query(_Doc).filter(_Doc.id == doc_id).first()
            if doc2:
                doc2.nextcloud_sync_status = "error"
                doc2.nextcloud_sync_error = str(e)[:500]
                db.commit()
        except Exception:
            pass  # best-effort; don't let status update failure crash the handler
    finally:
        db.close()


def setup_nextcloud_routes(upload_handler=None) -> APIRouter:
    router = APIRouter(prefix="/api/nextcloud", tags=["nextcloud"])

    # ── Accounts ──

    @router.get("/accounts")
    async def list_accounts(owner: Optional[str] = Depends(_require_owner)):
        return {"accounts": [_redact(a) for a in _load_accounts(owner)]}

    @router.post("/accounts")
    async def create_account(data: dict, owner: Optional[str] = Depends(_require_owner)):
        base_url = (data.get("base_url") or "").strip()
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        label = (data.get("label") or "").strip()
        if not (base_url and username and password):
            raise HTTPException(400, "base_url, username, and password are required")
        try:
            base_url = validate_nextcloud_url(base_url)
        except ValueError as e:
            raise HTTPException(400, str(e))
        from src.secret_storage import encrypt

        account = {
            "id": str(uuid.uuid4()),
            "label": label or username,
            "base_url": base_url,
            "username": username,
            "password": encrypt(password),
        }
        accounts = _load_accounts(owner)
        accounts.append(account)
        _save_accounts(owner, accounts)
        return _redact(account)

    @router.put("/accounts/{account_id}")
    async def update_account(account_id: str, data: dict, owner: Optional[str] = Depends(_require_owner)):
        account = _find_account(owner, account_id)
        if "base_url" in data and data["base_url"] is not None:
            try:
                account["base_url"] = validate_nextcloud_url((data["base_url"] or "").strip())
            except ValueError as e:
                raise HTTPException(400, str(e))
        if data.get("username"):
            account["username"] = data["username"].strip()
        if data.get("label"):
            account["label"] = data["label"].strip()
        new_pw = (data.get("password") or "").strip()
        if new_pw:
            from src.secret_storage import encrypt

            account["password"] = encrypt(new_pw)
        # Persist by replacing the matching row.
        accounts = _load_accounts(owner)
        for i, a in enumerate(accounts):
            if a.get("id") == account_id:
                accounts[i] = account
                break
        _save_accounts(owner, accounts)
        return _redact(account)

    @router.delete("/accounts/{account_id}")
    async def delete_account(account_id: str, owner: Optional[str] = Depends(_require_owner)):
        accounts = _load_accounts(owner)
        remaining = [a for a in accounts if a.get("id") != account_id]
        if len(remaining) == len(accounts):
            raise HTTPException(404, "Nextcloud account not found")
        _save_accounts(owner, remaining)
        return {"success": True}

    # ── Browsing (read-only) ──

    @router.post("/test")
    async def test_connection(data: dict, owner: Optional[str] = Depends(_require_owner)):
        """Verify credentials without saving.

        Accepts an ``account_id`` (test stored creds, owner-scoped), or inline
        ``base_url`` + ``username`` + ``password`` for an unsaved account. When
        ``account_id`` and ``password`` are both given, the inline password is
        tested against the account's stored URL/username — the CalDAV-style
        "test a newly typed password before saving" case.
        """
        from src.secret_storage import decrypt

        account_id = (data.get("account_id") or "").strip()
        password = (data.get("password") or "").strip()
        base_url = (data.get("base_url") or "").strip()
        username = (data.get("username") or "").strip()
        if account_id:
            account = _find_account(owner, account_id)  # 404 if it isn't this owner's
            base_url = base_url or (account.get("base_url") or "")
            username = username or (account.get("username") or "")
            if not password:
                password = decrypt(account.get("password") or "")
        if not (base_url and username and password):
            raise HTTPException(400, "Provide an account_id, or base_url + username + password")
        try:
            client = NextcloudClient(base_url, username, password)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        try:
            await asyncio.to_thread(client.ping)
        except NextcloudError as e:
            return {"ok": False, "error": str(e)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @router.get("/list")
    async def list_path(
        request: Request,
        account: str = Query(..., description="Account id"),
        path: str = Query("", description="Path relative to the user's Nextcloud home"),
        owner: Optional[str] = Depends(_require_owner),
    ):
        client = _client_for(_find_account(owner, account))
        try:
            entries = await asyncio.to_thread(client.list_dir, path)
        except NextcloudError as e:
            raise _map_nextcloud_error(e)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"account": account, "path": (path or "").strip("/"), "entries": entries}

    @router.get("/stat")
    async def stat_path(
        account: str = Query(...),
        path: str = Query(""),
        owner: Optional[str] = Depends(_require_owner),
    ):
        client = _client_for(_find_account(owner, account))
        try:
            entry = await asyncio.to_thread(client.stat, path)
        except NextcloudError as e:
            raise _map_nextcloud_error(e)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"account": account, "entry": entry}

    @router.get("/file")
    async def get_file(
        account: str = Query(...),
        path: str = Query(...),
        owner: Optional[str] = Depends(_require_owner),
    ):
        client = _client_for(_find_account(owner, account))
        try:
            content, content_type = await asyncio.to_thread(
                client.get_file, path, NEXTCLOUD_MAX_DOWNLOAD_BYTES
            )
        except NextcloudError as e:
            raise _map_nextcloud_error(e)
        except ValueError as e:
            raise HTTPException(400, str(e))
        name = (path or "").rsplit("/", 1)[-1] or "download"
        if not content_type:
            guessed, _ = mimetypes.guess_type(name)
            content_type = guessed or "application/octet-stream"
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{name}"'},
        )

    # ── Open in asset ──

    @router.post("/open-in-asset")
    async def open_in_asset(request: Request, data: dict, owner: Optional[str] = Depends(_require_owner)):
        """Import a Nextcloud file into the appropriate Odysseus asset.

        Accepts ``{"account_id": "...", "path": "...", "session_id": "..." (opt)}``.

        Based on server content-type the file is routed to:
          * Text/code  → Document (text editor)
          * PDF         → Document with pdf_source marker (PDF viewer)
          * Image       → Gallery (lightbox + metadata)
          * Other       → HTTP 400

        The created asset carries Nextcloud provenance fields so the UI can
        show the source and future writeback/sync can find it.
        """
        account_id = (data.get("account_id") or "").strip()
        path = (data.get("path") or "").strip()
        session_id = (data.get("session_id") or "").strip() or None
        if not account_id or not path:
            raise HTTPException(400, "account_id and path are required")

        # ── Dedup: return existing asset if this Nextcloud file was already imported ──
        from core.database import SessionLocal as _SL, Document as _Doc, GalleryImage as _GI
        _dup_db = _SL()
        try:
            # Check for an existing document (text/code or PDF) with this provenance.
            existing_doc = _dup_db.query(_Doc).filter(
                _Doc.source_nextcloud_account == account_id,
                _Doc.source_nextcloud_path == path,
                _Doc.is_active == True,
            ).first()
            if existing_doc:
                from routes.document_helpers import _doc_to_dict
                return {"type": "document", "document": _doc_to_dict(existing_doc)}
            # Check for an existing gallery image with this provenance.
            existing_img = _dup_db.query(_GI).filter(
                _GI.source_nextcloud_account == account_id,
                _GI.source_nextcloud_path == path,
            ).first()
            if existing_img:
                return {"type": "gallery_image", "image": {"id": existing_img.id, "filename": existing_img.filename}}
        finally:
            _dup_db.close()

        client = _client_for(_find_account(owner, account_id))

        # Light detection: a PROPFIND (stat) gets us the content-type without
        # downloading the body. get_file(path, 1) can't be used for this because
        # it checks content-length against max_bytes BEFORE downloading, so any
        # file larger than 1 byte would 413.
        try:
            stat_entry = await asyncio.to_thread(client.stat, path)
        except NextcloudError as e:
            raise _map_nextcloud_error(e)
        except ValueError as e:
            raise HTTPException(400, str(e))

        content_type = (stat_entry or {}).get("content_type") or ""

        # Fall back to extension-based detection if no content-type
        if not content_type:
            guessed, _ = mimetypes.guess_type(path)
            content_type = guessed or ""

        ct_lower = (content_type or "").lower()

        # ── Text / Code ──
        _text_ct = (
            "text/",
            "application/json",
            "application/xml",
            "application/javascript",
            "application/x-yaml",
            "application/x-python",
            "application/x-shellscript",
        )
        _text_exts = {
            ".py", ".js", ".ts", ".md", ".txt", ".html", ".css",
            ".json", ".yaml", ".yml", ".xml", ".csv", ".sh", ".bash",
            ".sql", ".rs", ".go", ".java", ".c", ".cpp", ".rb", ".php",
            ".toml", ".ini",
        }
        is_text = any(ct_lower.startswith(p) for p in _text_ct)
        if not is_text:
            ext = (Path(path).suffix or "").lower()
            is_text = ext in _text_exts

        if is_text:
            try:
                content_bytes, _ = await asyncio.to_thread(
                    client.get_file, path, NEXTCLOUD_MAX_DOWNLOAD_BYTES
                )
            except NextcloudError as e:
                raise _map_nextcloud_error(e)
            except ValueError as e:
                raise HTTPException(400, str(e))
            try:
                content_str = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(400, "File is not valid UTF-8 text; cannot open in editor")

            title = Path(path).name

            # Inline document creation (replicates POST /api/document logic).
            from core.database import SessionLocal, Document, DocumentVersion
            db = SessionLocal()
            try:
                from src.auth_helpers import require_privilege
                user = require_privilege(request, "can_use_documents")

                # Optional session validation
                session = None
                if session_id:
                    from routes.document_routes import _get_session_or_404
                    session = _get_session_or_404(db, session_id, user)

                # Detect language
                language = None
                try:
                    from src.agent_tools.document_tools import _sniff_doc_language
                    language = _sniff_doc_language(content_str)
                except Exception:
                    language = "markdown"

                doc_id = str(uuid.uuid4())
                ver_id = str(uuid.uuid4())

                doc = Document(
                    id=doc_id,
                    session_id=session_id,
                    title=title,
                    language=language,
                    current_content=content_str,
                    version_count=1,
                    is_active=True,
                    owner=user or (session.owner if session else None),
                    source_nextcloud_account=account_id,
                    source_nextcloud_path=path,
                    nextcloud_sync_status="synced",
                )
                ver = DocumentVersion(
                    id=ver_id,
                    document_id=doc_id,
                    version_number=1,
                    content=content_str,
                    summary="Imported from Nextcloud",
                    source="user",
                )
                db.add(doc)
                db.add(ver)
                db.commit()
                db.refresh(doc)

                from routes.document_helpers import _doc_to_dict
                return {"type": "document", "document": _doc_to_dict(doc)}
            except HTTPException:
                raise
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to create document from Nextcloud: {e}")
                raise HTTPException(500, f"Failed to create document: {e}")
            finally:
                db.close()

        # ── PDF ──
        _is_pdf = ct_lower == "application/pdf" or Path(path).suffix.lower() == ".pdf"
        if _is_pdf:
            if upload_handler is None:
                raise HTTPException(500, "Upload handler not configured")

            # Download full PDF binary (cap at a reasonable size).
            pdf_max = min(NEXTCLOUD_MAX_DOWNLOAD_BYTES, 50_000_000)
            try:
                pdf_bytes, _ = await asyncio.to_thread(client.get_file, path, pdf_max)
            except NextcloudError as e:
                raise _map_nextcloud_error(e)
            except ValueError as e:
                raise HTTPException(400, str(e))

            # Save to a temp file in the upload store.
            from src.pdf_forms import has_form_fields, extract_fields
            from src.pdf_form_doc import (
                save_field_sidecar,
                create_form_markdown_document,
                create_plain_pdf_document,
            )
            from src.document_processor import _process_pdf, strip_pdf_content_marker
            from core.database import SessionLocal as SL

            title = Path(path).stem

            # Write the PDF bytes to a temp file and register it via upload_handler.
            import tempfile
            import time
            tmp_dir = getattr(upload_handler, "upload_dir", None) or getattr(upload_handler, "base_dir", None)
            if tmp_dir is None:
                raise HTTPException(500, "Upload handler has no upload directory")

            upload_id = uuid.uuid4().hex
            upload_filename = upload_id  # no extension — _find_upload_path matches by bare id
            upload_path = os.path.join(tmp_dir, upload_filename)
            os.makedirs(tmp_dir, exist_ok=True)
            with open(upload_path, "wb") as f:
                f.write(pdf_bytes)

            # Register the upload so resolve_upload works downstream.
            meta = {
                "id": upload_id,
                "name": upload_filename,
                "original_name": Path(path).name,
                "stored_name": upload_filename,
                "size": len(pdf_bytes),
                "uploaded_at": time.time(),
                "path": upload_path,
            }
            db_index = getattr(upload_handler, "_load_upload_index", None)
            if db_index is not None:
                try:
                    idx = db_index()
                    if isinstance(idx, dict):
                        idx[upload_id] = meta
                        _save = getattr(upload_handler, "_save_upload_index", None)
                        if _save:
                            _save(idx)
                except Exception:
                    pass

            # Process the PDF
            try:
                body_text = strip_pdf_content_marker(_process_pdf(upload_path, owner=owner))
            except Exception:
                body_text = None

            is_form = False
            try:
                is_form = has_form_fields(upload_path)
            except Exception as e:
                logger.warning(f"has_form_fields failed for {upload_path}: {e}")

            from core.database import SessionLocal as SL2
            if is_form:
                fields = extract_fields(upload_path)
                save_field_sidecar(upload_path, fields)
                doc_id = create_form_markdown_document(
                    session_id=session_id,
                    fields=fields,
                    upload_id=upload_id,
                    title=title,
                    intro_text=body_text,
                )
            else:
                doc_id = create_plain_pdf_document(
                    session_id=session_id,
                    upload_id=upload_id,
                    title=title,
                    body_text=body_text,
                )

            if not doc_id:
                raise HTTPException(500, "Failed to create document for PDF")

            # Stamp Nextcloud provenance on the created document.
            db = SL2()
            try:
                from core.database import Document as Doc
                doc = db.query(Doc).filter(Doc.id == doc_id).first()
                if not doc:
                    raise HTTPException(500, "Created document not found")
                if not doc.owner and owner:
                    doc.owner = owner
                doc.source_nextcloud_account = account_id
                doc.source_nextcloud_path = path
                doc.nextcloud_sync_status = "synced"
                db.commit()
                db.refresh(doc)
                from routes.document_helpers import _doc_to_dict
                return {"type": "document", "document": _doc_to_dict(doc)}
            finally:
                db.close()

        # ── Image ──
        _is_image = ct_lower.startswith("image/")
        if not _is_image:
            img_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
            _is_image = (Path(path).suffix or "").lower() in img_exts

        if _is_image:
            # Download image binary
            img_max = min(NEXTCLOUD_MAX_DOWNLOAD_BYTES, 50_000_000)
            try:
                img_bytes, _ = await asyncio.to_thread(client.get_file, path, img_max)
            except NextcloudError as e:
                raise _map_nextcloud_error(e)
            except ValueError as e:
                raise HTTPException(400, str(e))

            from core.database import SessionLocal, GalleryImage
            from routes.gallery.gallery_helpers import _extract_exif

            db = SessionLocal()
            try:
                from src.auth_helpers import get_current_user
                user = get_current_user(request)

                # Dedup via SHA-256
                file_hash = hashlib.sha256(img_bytes).hexdigest()
                _dup_q = db.query(GalleryImage).filter(
                    GalleryImage.file_hash == file_hash,
                    GalleryImage.is_active == True,
                )
                if user:
                    _dup_q = _dup_q.filter(GalleryImage.owner == user)
                existing = _dup_q.first()
                if existing:
                    # Still stamp provenance if missing
                    if not getattr(existing, "source_nextcloud_account", None):
                        existing.source_nextcloud_account = account_id
                        existing.source_nextcloud_path = path
                        db.commit()
                    from routes.gallery.gallery_helpers import _image_to_dict
                    return {"type": "gallery_image", "image": _image_to_dict(existing)}

                img_dir = Path(GENERATED_IMAGES_DIR)
                img_dir.mkdir(parents=True, exist_ok=True)

                ext = (Path(path).suffix or ".png").lstrip(".").lower()
                filename = f"{uuid.uuid4().hex[:12]}.{ext}"
                img_path = img_dir / filename
                img_path.write_bytes(img_bytes)

                exif = _extract_exif(img_bytes)
                original_name = Path(path).stem

                img_id = str(uuid.uuid4())
                db.add(GalleryImage(
                    id=img_id,
                    filename=filename,
                    prompt=original_name,
                    model="nextcloud",
                    owner=user,
                    file_hash=file_hash,
                    file_size=len(img_bytes),
                    width=exif.get("width"),
                    height=exif.get("height"),
                    taken_at=exif.get("taken_at"),
                    camera_make=exif.get("camera_make"),
                    camera_model=exif.get("camera_model"),
                    gps_lat=exif.get("gps_lat"),
                    gps_lng=exif.get("gps_lng"),
                    source_nextcloud_account=account_id,
                    source_nextcloud_path=path,
                ))
                db.commit()
                db.refresh(db.query(GalleryImage).filter(GalleryImage.id == img_id).first())
                img = db.query(GalleryImage).filter(GalleryImage.id == img_id).first()
                from routes.gallery.gallery_helpers import _image_to_dict
                return {"type": "gallery_image", "image": _image_to_dict(img)}
            finally:
                db.close()

        # ── Unsupported ──
        raise HTTPException(400, f"Unsupported file type: {content_type or 'unknown'}")

    # ── Manual sync trigger ──

    @router.post("/sync-docs")
    async def sync_docs(owner: Optional[str] = Depends(_require_owner)):
        """Manually trigger a Nextcloud document sync for the current user."""
        from src.nextcloud_sync import sync_nextcloud_documents
        result = await sync_nextcloud_documents(owner=owner)
        return result

    return router
