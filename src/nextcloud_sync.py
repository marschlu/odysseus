"""Nextcloud file sync — periodic check for remotely-changed documents.

Polls every Nextcloud-sourced document via WebDAV PROPFIND (stat) and
compares the remote modification time against the last-known sync timestamp.
When a remote file is newer, downloads the content into a new DocumentVersion.

Design notes:
- Follows the :mod:`src.caldav_sync` pattern (one-way pull, remote → local).
- The sync is best-effort — a failure on one document never aborts the others.
- All WebDAV operations go through ``asyncio.to_thread`` so the FastAPI event
  loop stays free (same pattern as CalDAV sync and Nextcloud routes).
- Timestamps are compared as timezone-aware datetimes so ISO‑8601 strings from
  different zones are ordered correctly.
- ``NEXTCLOUD_MAX_DOWNLOAD_BYTES`` caps which files we download; a remote file
  larger than the cap is skipped with an error status instead of blowing memory.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.database import Document, DocumentVersion, SessionLocal
from src.constants import NEXTCLOUD_MAX_DOWNLOAD_BYTES
from src.nextcloud_client import NextcloudError

logger = logging.getLogger(__name__)


def _parse_iso_to_utc(raw: Optional[str]) -> Optional[datetime]:
    """Convert an ISO‑8601 string (with or without TZ suffix) to a UTC datetime.

    Returns ``None`` when *raw* is empty/None or unparseable, so comparisons
    always degrade safely (e.g. ``modified`` is treated as "unknown" and the
    document is not downloaded).
    """
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        # Python 3.11+ datetime.fromisoformat handles Z, +00:00, +05:30, etc.
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        # Fallback: try parsing with a few common formats for robustness
        # when the server sends non-standard strings.
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        # Naive datetime — assume UTC (the server's clock is the reference).
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def sync_nextcloud_documents(owner: Optional[str] = None) -> dict:
    """Check all Nextcloud-sourced documents for remote changes and pull in
    newer content.

    When *owner* is ``None`` (the background-task case), the function iterates
    every active document with Nextcloud provenance across all users — no
    account is silently skipped.  When *owner* is set (the manual endpoint
    case), only that user's documents are checked.

    Returns a summary dict with counts::

        {"checked": N, "updated": N, "errors": N}
    """
    from routes.nextcloud_routes import _client_for, _find_account

    result = {"checked": 0, "updated": 0, "errors": 0}

    db = SessionLocal()
    try:
        query = db.query(Document).filter(
            Document.source_nextcloud_account.isnot(None),
            Document.source_nextcloud_path.isnot(None),
            Document.is_active.is_(True),
        )
        if owner is not None:
            query = query.filter(Document.owner == owner)

        docs = query.all()
        for doc in docs:
            result["checked"] += 1
            doc_owner = getattr(doc, "owner", None)
            account_id = doc.source_nextcloud_account
            path = doc.source_nextcloud_path

            if not path:
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = "Missing source path"
                continue

            # Resolve account credentials scoped to this document's owner.
            try:
                account = _find_account(doc_owner, account_id)
                client = _client_for(account)
            except Exception as e:
                logger.warning(
                    "Nextcloud sync: cannot resolve account %s for owner %s: %s",
                    account_id, doc_owner, e,
                )
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = str(e)[:500]
                continue

            # Check remote modification time.
            try:
                stat_entry = await asyncio.to_thread(client.stat, path)
            except NextcloudError as e:
                logger.warning(
                    "Nextcloud sync: stat failed for %s/%s: %s",
                    account_id, path, e,
                )
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = str(e)[:500]
                continue
            except Exception as e:
                logger.warning(
                    "Nextcloud sync: stat unexpected error for %s/%s: %s",
                    account_id, path, e,
                )
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = str(e)[:500]
                continue

            remote_modified = _parse_iso_to_utc(stat_entry.get("modified"))
            last_synced = doc.nextcloud_synced_at

            # Convert last_synced to UTC for safe comparison.
            if last_synced is not None and last_synced.tzinfo is None:
                last_synced = last_synced.replace(tzinfo=timezone.utc)

            # Skip when the remote timestamp is unparseable (unknown).
            if remote_modified is None:
                # The server did not return a usable modification date.
                # When we've *never* synced before, don't just skip — pull
                # the content anyway since the first sync should always
                # establish a baseline.
                if last_synced is None:
                    logger.info(
                        "Nextcloud sync: no modified date for %s/%s but never synced; pulling baseline",
                        account_id, path,
                    )
                    # fall through to download below
                else:
                    logger.info(
                        "Nextcloud sync: no usable modified date for %s/%s; skipping",
                        account_id, path,
                    )
                    continue

            # Skip when the remote file is not newer than our last sync.
            if last_synced is not None and remote_modified <= last_synced:
                continue

            # Remote is newer (or we have never synced) — pull content.
            try:
                content_bytes, _ = await asyncio.to_thread(
                    client.get_file, path, NEXTCLOUD_MAX_DOWNLOAD_BYTES
                )
            except NextcloudError as e:
                logger.warning(
                    "Nextcloud sync: download failed for %s/%s: %s",
                    account_id, path, e,
                )
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = str(e)[:500]
                continue
            except Exception as e:
                logger.warning(
                    "Nextcloud sync: download unexpected error for %s/%s: %s",
                    account_id, path, e,
                )
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = str(e)[:500]
                continue

            # Decode content and create a new version.
            try:
                content_str = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # Binary file — we cannot treat it as document text.
                result["errors"] += 1
                doc.nextcloud_sync_status = "error"
                doc.nextcloud_sync_error = "File is not valid UTF-8 text; cannot sync as document"
                continue

            ver_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            version = DocumentVersion(
                id=ver_id,
                document_id=doc.id,
                version_number=(doc.version_count or 0) + 1,
                content=content_str,
                summary="Synced from Nextcloud (remote changed)",
                source="nextcloud_sync",
            )
            db.add(version)

            doc.current_content = content_str
            doc.version_count = (doc.version_count or 0) + 1
            doc.nextcloud_sync_status = "synced"
            doc.nextcloud_synced_at = now
            doc.nextcloud_sync_error = None
            result["updated"] += 1

            logger.info(
                "Nextcloud sync: updated doc %s from %s/%s (remote newer)",
                doc.id, account_id, path,
            )

        db.commit()

    except Exception as e:
        logger.exception("Nextcloud sync: batch error")
        result["errors"] += 1
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()

    if result["checked"] > 0 or result["updated"] > 0 or result["errors"] > 0:
        logger.info(
            "Nextcloud sync finished: checked=%d updated=%d errors=%d",
            result["checked"], result["updated"], result["errors"],
        )

    return result
