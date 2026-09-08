"""User-session transport, isolated from both organization and project API keys."""

import re
from http.cookies import CookieError, SimpleCookie

from app.core.errors import ApiError


class SessionClient:
    def __init__(self, http, cookie):
        self.http = http
        self._cookie = cookie

    def require(self):
        raw = self._cookie
        if not raw:
            raise ValueError("Set LANGFUSE_SESSION_COOKIE in .env to execute Playground")
        if len(raw) > 32768 or any(ord(char) < 32 or ord(char) > 126 for char in raw):
            raise ValueError("LANGFUSE_SESSION_COOKIE must be a single ASCII Cookie header value")
        parsed = SimpleCookie()
        try:
            parsed.load(raw)
        except CookieError:
            raise ValueError("LANGFUSE_SESSION_COOKIE is not a valid Cookie header value") from None
        parts = [
            f"{name}={morsel.coded_value}"
            for name, morsel in parsed.items()
            if re.fullmatch(
                r"(?:__Secure-|__Host-)?(?:next-auth|authjs)\.session-token(?:\.\d+)?", name
            )
            and morsel.value
        ]
        if not parts:
            raise ValueError("LANGFUSE_SESSION_COOKIE contains no session-token cookie")
        return "; ".join(parts)

    def complete(self, project_id, body):
        cookie = self.require()
        if not project_id or body.get("projectId") != project_id:
            raise ValueError("Playground project does not match the project context")
        try:
            return self.http.request(
                "POST", "/api/chatCompletion", headers={"Cookie": cookie}, body=body
            )
        except ApiError as error:
            if error.status == 401:
                raise RuntimeError(
                    "Playground session expired or invalid; refresh LANGFUSE_SESSION_COOKIE"
                ) from None
            if error.status == 403:
                raise RuntimeError(
                    "The logged-in user cannot execute Playground in this project"
                ) from None
            raise RuntimeError(
                f"Playground HTTP {error.status}; check server logs. No automatic retry"
            ) from None
        except RuntimeError:
            raise RuntimeError(
                "Playground request failed; the model may have run. No automatic retry"
            ) from None
