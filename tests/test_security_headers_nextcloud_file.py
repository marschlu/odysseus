"""Security headers: Nextcloud file route no longer needs framing.

Since the document-editing layer has been removed, /api/nextcloud/file
opens in a new tab and does NOT need to be embeddable in an iframe.
All downstream providers get the default DENY.
"""

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from core.middleware import SecurityHeadersMiddleware


def _client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/nextcloud/file")
    async def nc_file():
        return Response(b"content", media_type="text/plain")

    return TestClient(app)


def test_nextcloud_file_is_not_framable():
    response = _client().get("/api/nextcloud/file?account=a&path=x.txt")

    assert response.headers["X-Frame-Options"] == "DENY"
