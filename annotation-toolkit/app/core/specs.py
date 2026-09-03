"""Platform-neutral task and record specifications."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class FieldSpec:
    """A field shown to an annotator."""

    name: str
    title: str
    required: bool = False
    use_markdown: bool = False


@dataclass(frozen=True)
class QuestionSpec:
    """A platform-neutral annotation question."""

    kind: Literal["label", "multi_label", "text"]
    name: str
    title: str
    description: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    required: bool = False
    visible_labels: int | None = None


@dataclass(frozen=True)
class MetadataSpec:
    """Metadata attached to a record."""

    name: str
    title: str
    visible_for_annotators: bool = False


@dataclass(frozen=True)
class TaskSpec:
    """A complete annotation task independent of any platform SDK."""

    guidelines: str
    fields: tuple[FieldSpec, ...]
    questions: tuple[QuestionSpec, ...]
    metadata: tuple[MetadataSpec, ...]


@dataclass(frozen=True)
class RecordSpec:
    """A normalized annotation record independent of any platform SDK."""

    id: str
    fields: Mapping[str, str]
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class ProfileInput:
    """Rows normalized by a business profile from one source format."""

    source_format: str
    rows: list[dict[str, str]]
