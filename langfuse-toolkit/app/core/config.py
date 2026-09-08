"""Independent credentials for each scope; loading config has no network effects."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class KeyPair:
    public: str = field(default="", repr=False)
    secret: str = field(default="", repr=False)

    def require(self, prefix):
        if not self.public.strip() or not self.secret.strip():
            raise ValueError(f"Set {prefix}_PUBLIC_KEY and {prefix}_SECRET_KEY")
        return self.public, self.secret


@dataclass(frozen=True)
class Config:
    base_url: str = ""
    project_id: str = ""
    project_keys: KeyPair = field(default_factory=KeyPair, repr=False)
    organization_keys: KeyPair = field(default_factory=KeyPair, repr=False)
    session_cookie: str = field(default="", repr=False)

    @classmethod
    def load(cls, path: Path):
        values = {**dotenv_values(path), **os.environ}

        def pair(prefix):
            return KeyPair(
                values.get(prefix + "_PUBLIC_KEY") or "", values.get(prefix + "_SECRET_KEY") or ""
            )

        # The old names remain project-only. Never infer organization credentials from them.
        project_prefix = "LANGFUSE"
        for source in (os.environ, values):
            if any(source.get("LANGFUSE_PROJECT_" + name) for name in ("PUBLIC_KEY", "SECRET_KEY")):
                project_prefix = "LANGFUSE_PROJECT"
                break
            if any(source.get("LANGFUSE_" + name) for name in ("PUBLIC_KEY", "SECRET_KEY")):
                break
        return cls(
            base_url=values.get("LANGFUSE_BASE_URL") or "",
            project_id=values.get("LANGFUSE_PROJECT_ID") or "",
            project_keys=pair(project_prefix),
            organization_keys=pair("LANGFUSE_ORG"),
            session_cookie=values.get("LANGFUSE_SESSION_COOKIE") or "",
        )
