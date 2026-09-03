"""Contract implemented by annotation business profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.core import ProfileInput, RecordSpec, TaskSpec


class AnnotationProfile(Protocol):
    """Business behavior consumed by the framework and platform adapters."""

    name: str
    modes: tuple[str, ...]
    default_dataset_prefix: str
    default_input_name: str
    default_user_prefix: str
    sampling_fields: tuple[str, str]

    def load_input(self, path: Path) -> ProfileInput: ...

    def task_spec(self, mode: str) -> TaskSpec: ...

    def record_spec(self, row: dict[str, str], mode: str) -> RecordSpec: ...

    def default_dataset_name(self, mode: str) -> str: ...
