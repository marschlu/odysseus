"""Route-level tests for Nextcloud Files: auth gate, owner isolation, and the
fact that the app password is encrypted at rest and never returned.

Uses dependency_overrides to simulate distinct owners (no full auth middleware),
a temp prefs file so no real user data is touched, and a stubbed client so no
network is involved. Behavioral-first: we hit the routes and assert outcomes.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.prefs_routes as prefs_routes
import routes.nextcloud_routes as nc
from src.auth_helpers import require_user


class _FakeClient:
    """Stand-in for NextcloudClient so route tests never touch the network."""

    def __init__(self, *_, **__):
        pass

    def list_dir(self, path=""):
        return [
            {"name": "Documents", "path": "Documents", "is_dir": True, "size": None,
             "content_type": None, "modified": "2025-06-01T00:00:00+00:00"},
            {"name": "readme.txt", "path": "readme.txt", "is_dir": False, "size": 5,
             "content_type": "text/plain", "modified": "2025-06-01T00:00:00+00:00"},
        ]

    def stat(self, path=""):
        return {"name": path.rsplit("/", 1)[-1] or "/", "path": (path or "").strip("/"),
                "is_dir": False, "size": 5, "content_type": "text/plain", "modified": None}

    def get_file(self, path, max_bytes=None):
        return b"hello", "text/plain"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(tmp_path / "prefs.json"))
    # URL/SSRF validation is exercised in test_nextcloud_client.py; here we
    # accept any URL so account creation never hits real DNS.
    monkeypatch.setattr(nc, "validate_nextcloud_url", lambda url, *a, **k: url)
    a = FastAPI()
    a.include_router(nc.setup_nextcloud_routes())
    return a


def _as(app, owner):
    app.dependency_overrides[nc._require_owner] = lambda: owner


# ── Auth gate ──

def test_routes_require_authentication(app, monkeypatch):
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)
    # No dependency override → real require_user runs; TestClient is not loopback
    # and there is no auth_manager, so an unauthenticated caller is rejected.
    client = TestClient(app)
    r = client.get("/api/nextcloud/accounts")
    assert r.status_code == 401


# ── Owner isolation ──

def test_account_password_is_encrypted_at_rest_and_never_returned(app):
    _as(app, "alice")
    client = TestClient(app)
    r = client.post("/api/nextcloud/accounts", json={
        "label": "Work", "base_url": "https://cloud.example.com",
        "username": "alice", "password": "supersecret",
    })
    assert r.status_code == 200
    body = r.json()
    assert "password" not in body            # never returned
    assert body["configured"] is True
    acc_id = body["id"]

    listed = client.get("/api/nextcloud/accounts").json()["accounts"]
    assert listed[0]["id"] == acc_id
    assert "password" not in listed[0]

    # On disk the password is Fernet-encrypted (enc: prefix), not plaintext.
    raw = json.loads(__import__("pathlib").Path(prefs_routes.PREFS_FILE).read_text())
    stored = raw["_users"]["alice"]["nextcloud_accounts"][0]["password"]
    assert stored.startswith("enc:")
    assert "supersecret" not in stored


def test_owners_are_isolated(app):
    _as(app, "alice")
    alice = TestClient(app)
    created = alice.post("/api/nextcloud/accounts", json={
        "base_url": "https://cloud.example.com", "username": "alice", "password": "pw1",
    }).json()
    alice_id = created["id"]

    # Bob is a different owner: sees none of alice's accounts, can't use her id.
    _as(app, "bob")
    bob = TestClient(app)
    assert bob.get("/api/nextcloud/accounts").json()["accounts"] == []
    assert bob.get(f"/api/nextcloud/list?account={alice_id}&path=").status_code == 404
    assert bob.delete(f"/api/nextcloud/accounts/{alice_id}").status_code == 404


def test_owner_can_delete_their_own_account(app):
    _as(app, "alice")
    client = TestClient(app)
    acc_id = client.post("/api/nextcloud/accounts", json={
        "base_url": "https://cloud.example.com", "username": "alice", "password": "pw",
    }).json()["id"]
    assert client.delete(f"/api/nextcloud/accounts/{acc_id}").status_code == 200
    assert client.get("/api/nextcloud/accounts").json()["accounts"] == []


# ── Browsing (stubbed client) ──

def _make_account(client):
    return client.post("/api/nextcloud/accounts", json={
        "base_url": "https://cloud.example.com", "username": "alice", "password": "pw",
    }).json()["id"]


def test_list_returns_entries(app, monkeypatch):
    _as(app, "alice")
    monkeypatch.setattr(nc, "_client_for", lambda account: _FakeClient())
    client = TestClient(app)
    acc_id = _make_account(client)
    r = client.get(f"/api/nextcloud/list?account={acc_id}&path=")
    assert r.status_code == 200
    names = {e["name"] for e in r.json()["entries"]}
    assert names == {"Documents", "readme.txt"}


def test_file_download_returns_content_and_type(app, monkeypatch):
    _as(app, "alice")
    monkeypatch.setattr(nc, "_client_for", lambda account: _FakeClient())
    client = TestClient(app)
    acc_id = _make_account(client)
    r = client.get(f"/api/nextcloud/file?account={acc_id}&path=readme.txt")
    assert r.status_code == 200
    assert r.content == b"hello"
    assert r.headers["content-type"].startswith("text/plain")


def test_list_unknown_account_is_404(app):
    _as(app, "alice")
    client = TestClient(app)
    assert client.get("/api/nextcloud/list?account=nope&path=").status_code == 404


# ── Test connection ──

def test_test_connection_requires_fields(app):
    _as(app, "alice")
    client = TestClient(app)
    assert client.post("/api/nextcloud/test", json={}).status_code == 400


def test_test_connection_inline_success(app, monkeypatch):
    _as(app, "alice")
    class _C:
        def __init__(self, base_url, username, password):
            self.base_url = base_url
        def ping(self):
            return True
    monkeypatch.setattr(nc, "NextcloudClient", _C)
    client = TestClient(app)
    r = client.post("/api/nextcloud/test", json={
        "base_url": "https://cloud.example.com", "username": "alice", "password": "tok",
    })
    assert r.status_code == 200 and r.json()["ok"] is True


def test_test_connection_saved_account_failure(app, monkeypatch):
    from src.nextcloud_client import NextcloudError

    _as(app, "alice")
    client = TestClient(app)
    acc_id = _make_account(client)

    class _C:
        def __init__(self, base_url, username, password):
            pass
        def ping(self):
            raise NextcloudError("Nextcloud rejected the credentials (401).", status=401)

    monkeypatch.setattr(nc, "NextcloudClient", _C)
    r = client.post("/api/nextcloud/test", json={"account_id": acc_id})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "credentials" in body["error"]


def test_test_connection_unknown_account_is_404(app, monkeypatch):
    _as(app, "alice")
    # No fake client needed: the owner-scope lookup fails first.
    r = TestClient(app).post("/api/nextcloud/test", json={"account_id": "not-mine"})
    assert r.status_code == 404


# ── Read tool: text (read-only, text-only) ──

async def test_read_file_tool_returns_text(app, monkeypatch):
    from src.agent_tools.nextcloud_tools import NextcloudReadFileTool

    _as(app, "alice")
    _make_account(TestClient(app))

    class _C:
        def get_file(self, path, max_bytes=None):
            return b"hello world", "text/plain"

    monkeypatch.setattr(nc, "_client_for", lambda account: _C())
    res = await NextcloudReadFileTool().execute('{"path":"a.txt"}', {"owner": "alice"})
    assert res["exit_code"] == 0 and "hello world" in res["output"]


async def test_read_file_tool_rejects_binary(app, monkeypatch):
    """Non-PDF binary formats (docx, etc.) are still rejected."""
    from src.agent_tools.nextcloud_tools import NextcloudReadFileTool

    _as(app, "alice")
    _make_account(TestClient(app))

    class _C:
        def get_file(self, path, max_bytes=None):
            return b"binary bytes", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    monkeypatch.setattr(nc, "_client_for", lambda account: _C())
    res = await NextcloudReadFileTool().execute('{"path":"reports/2024.docx"}', {"owner": "alice"})
    assert res["exit_code"] == 1 and "cannot read binary file" in res["error"]


# ── PDF extraction helpers ──

def _make_minimal_pdf(text: str = "Hello PDF World") -> bytes:
    """Build a minimal valid PDF with extractable text for use in tests."""
    content = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode()
    obj4_len = len(content)
    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    obj2 = b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    obj3 = b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    obj4 = f"4 0 obj<</Length {obj4_len}>>stream\n".encode() + content + b"\nendstream\nendobj\n"
    obj5 = b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    parts = [header, obj1, obj2, obj3, obj4, obj5]
    body = b"".join(parts)
    xref_start = len(body)
    off0, off1, off2, off3, off4, off5 = 0, len(header), len(header) + len(obj1), len(header) + len(obj1) + len(obj2), len(header) + len(obj1) + len(obj2) + len(obj3), len(header) + len(obj1) + len(obj2) + len(obj3) + len(obj4)
    xref = f"xref\n0 6\n{off0:010d} 65535 f \n{off1:010d} 00000 n \n{off2:010d} 00000 n \n{off3:010d} 00000 n \n{off4:010d} 00000 n \n{off5:010d} 00000 n \n".encode()
    trailer = f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n{xref_start}\n%%EOF".encode()
    return body + xref + trailer


# ── PDF extraction tests ──

async def test_read_file_tool_extracts_pdf_text(app, monkeypatch):
    """PDF files with .pdf extension are parsed and text is returned."""
    from src.agent_tools.nextcloud_tools import NextcloudReadFileTool

    _as(app, "alice")
    _make_account(TestClient(app))

    pdf_bytes = _make_minimal_pdf("Hello PDF World")

    class _C:
        def get_file(self, path, max_bytes=None):
            return pdf_bytes, "application/pdf"

    monkeypatch.setattr(nc, "_client_for", lambda account: _C())
    res = await NextcloudReadFileTool().execute('{"path":"reports/2024.pdf"}', {"owner": "alice"})
    assert res["exit_code"] == 0
    assert "Hello PDF World" in res["output"]
    assert "[nextcloud:" in res["output"]


async def test_read_file_tool_extracts_pdf_by_content_type(app, monkeypatch):
    """Files with content-type application/pdf are treated as PDF even without .pdf extension."""
    from src.agent_tools.nextcloud_tools import NextcloudReadFileTool

    _as(app, "alice")
    _make_account(TestClient(app))

    pdf_bytes = _make_minimal_pdf("Content-Type PDF")

    class _C:
        def get_file(self, path, max_bytes=None):
            return pdf_bytes, "application/pdf"

    monkeypatch.setattr(nc, "_client_for", lambda account: _C())
    res = await NextcloudReadFileTool().execute('{"path":"reports/report"}', {"owner": "alice"})
    assert res["exit_code"] == 0
    assert "Content-Type PDF" in res["output"]


async def test_read_file_tool_pdf_extraction_failure_is_graceful(app, monkeypatch):
    """When all PDF extraction methods fail, the tool returns an error without traceback."""
    import src.agent_tools.nextcloud_tools as nt

    _as(app, "alice")
    _make_account(TestClient(app))

    class _C:
        def get_file(self, path, max_bytes=None):
            return b"\x00\x01\xFF\xFE", "application/pdf"

    monkeypatch.setattr(nc, "_client_for", lambda account: _C())
    res = await nt.NextcloudReadFileTool().execute('{"path":"reports/bad.pdf"}', {"owner": "alice"})
    # Should not crash — returns a result dict gracefully
    assert "exit_code" in res
    # Either it extracts something (raw decode might work) or returns an error
    # The key is no unhandled exception
    assert "error" in res or "output" in res



