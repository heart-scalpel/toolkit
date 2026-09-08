"""Command data passed between adapters, application services and workflows."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    scope: str
    resource: str
    action: str
    arguments: dict = field(default_factory=dict)
    dry_run: bool = False
    confirmed: bool = False

    @property
    def name(self):
        scope = "org" if self.scope == "organization" else self.scope
        if self.resource in ("health", "info", "check"):
            return f"{scope} {self.resource}"
        return f"{scope} {self.resource} {self.action}"


@dataclass(frozen=True)
class PreparedCommand:
    command: Command
    payload: object = None
    delete_target: str | None = None
