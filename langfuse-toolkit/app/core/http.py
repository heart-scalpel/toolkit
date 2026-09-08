"""HTTP transport shared by scope clients; no domain or CLI dependencies."""

from urllib.parse import urlsplit

import httpx

from app.core.errors import ApiError


class HttpClient:
    def __init__(self, base_url, *, auth=None, timeout=30, transport=None):
        url = urlsplit(base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("LANGFUSE_BASE_URL must be a plain http(s) URL")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            auth=auth,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self._http.close()

    def request(self, method, path, *, params=None, body=None, headers=None):
        if not path.startswith("/api/") or any(char in path for char in "\r\n?#"):
            raise ValueError("API path must be a relative /api/ path without query or fragment")
        try:
            response = self._http.request(
                method, path.lstrip("/"), params=params, json=body, headers=headers
            )
        except httpx.HTTPError:
            suffix = (
                " The write outcome is unknown; inspect before retrying." if method != "GET" else ""
            )
            raise RuntimeError(f"{method} {path}: connection failed.{suffix}") from None
        if not 200 <= response.status_code < 300:
            raise ApiError(method, path, response.status_code)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise RuntimeError(f"{method} {path}: server returned invalid JSON") from None
