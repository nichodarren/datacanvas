"""Data identity entities (DESIGN.md §9.2).

``DatasetVersion`` and ``SchemaContract`` carry INV-2 and INV-3. These classes
are frozen, which stops mutation inside this process; the database enforces the
same rule with triggers (§9.2, §13.7). Two layers on purpose — a frozen
dataclass says nothing about what a stray ``UPDATE`` can do.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ._checks import ensure_aware, ensure_non_empty
from .enums import ColumnRole, LogicalType
from .errors import InvariantViolation
from .ids import (
    DatasetId,
    DatasetVersionId,
    ProjectId,
    SchemaContractId,
    SourceFileId,
    UserId,
)


@dataclass(frozen=True, slots=True)
class Dataset:
    """Logical identity of "a dataset" over time. Holds no data itself."""

    id: DatasetId
    project_id: ProjectId
    name: str
    created_at: datetime

    def __post_init__(self) -> None:
        ensure_aware(self.created_at, "created_at")
        ensure_non_empty(self.name, "name")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """Immutable (INV-2). Only created or deleted, never updated.

    ``parquet_uri`` is a ``storage://`` reference, never a filesystem path: the
    only thing allowed to resolve it into something readable is the object store,
    and only when handed a ``DataHandle`` (§13.3.1 L3).
    """

    id: DatasetVersionId
    dataset_id: DatasetId
    version_no: int
    content_hash: str
    parquet_uri: str
    row_count: int
    column_count: int
    byte_size: int
    ingested_at: datetime
    ingested_by: UserId
    ingest_options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_aware(self.ingested_at, "ingested_at")
        ensure_non_empty(self.content_hash, "content_hash")
        ensure_non_empty(self.parquet_uri, "parquet_uri")
        if self.version_no < 1:
            raise InvariantViolation("version_no starts at 1")
        for name, value in (
            ("row_count", self.row_count),
            ("column_count", self.column_count),
            ("byte_size", self.byte_size),
        ):
            if value < 0:
                raise InvariantViolation(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class SourceFile:
    """The uploaded file kept verbatim, for audit and re-parse (§9.2).

    ``original_filename`` is metadata shown to the user and never part of a
    storage path — paths use UUIDs (§13.6, path traversal via filename).
    """

    id: SourceFileId
    dataset_version_id: DatasetVersionId
    original_filename: str
    mime_detected: str
    byte_size: int
    storage_uri: str

    def __post_init__(self) -> None:
        ensure_non_empty(self.storage_uri, "storage_uri")
        if self.byte_size < 0:
            raise InvariantViolation("byte_size must not be negative")


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column's interpretation inside a SchemaContract (§9.2)."""

    name: str
    ordinal: int
    physical_type: str
    logical_type: LogicalType
    role: ColumnRole | None = None
    format_hint: str | None = None
    null_markers: tuple[str, ...] = ()
    detection_confidence: float = 1.0
    #: Why the detector chose this type, in one sentence.
    #:
    #: Added 2026-07-29. FR-B.3 requires the detection be **shown for
    #: correction**, and a bare confidence of 0.5 gives a person nothing to
    #: agree or disagree with. *"97.0% of values are numeric, but 150 are not"*
    #: does — it names the thing they would have to go and look at.
    detection_reason: str = ""
    overridden_by: UserId | None = None

    def __post_init__(self) -> None:
        ensure_non_empty(self.name, "name")
        if self.ordinal < 0:
            raise InvariantViolation("ordinal must not be negative")
        if not 0.0 <= self.detection_confidence <= 1.0:
            raise InvariantViolation(
                f"detection_confidence must be within 0..1, got {self.detection_confidence}"
            )

    @property
    def is_user_overridden(self) -> bool:
        return self.overridden_by is not None


@dataclass(frozen=True, slots=True)
class SchemaContract:
    """Versioned interpretation of a DatasetVersion. Never updated (INV-3).

    ``version_no`` 1 is always pure auto-detection; every user correction
    produces a new version whose ``derived_from`` points at its predecessor.
    """

    id: SchemaContractId
    dataset_version_id: DatasetVersionId
    version_no: int
    columns: tuple[ColumnSpec, ...]
    created_at: datetime
    created_by: UserId | None = None
    derived_from: SchemaContractId | None = None

    def __post_init__(self) -> None:
        ensure_aware(self.created_at, "created_at")
        if self.version_no < 1:
            raise InvariantViolation("version_no starts at 1")
        if self.version_no == 1 and self.derived_from is not None:
            raise InvariantViolation("version 1 is auto-detected and derives from nothing")
        if self.version_no > 1 and self.derived_from is None:
            raise InvariantViolation("a corrected contract must record what it derives from")

        names = [c.name for c in self.columns]
        if len(names) != len(set(names)):
            raise InvariantViolation("column names must be unique within a contract")
        ordinals = sorted(c.ordinal for c in self.columns)
        if ordinals != list(range(len(self.columns))):
            raise InvariantViolation("ordinals must be a dense 0-based range")

    def column(self, name: str) -> ColumnSpec:
        for spec in self.columns:
            if spec.name == name:
                return spec
        raise InvariantViolation(f"no column named {name!r} in this contract")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in sorted(self.columns, key=lambda c: c.ordinal))


__all__ = [
    "ColumnSpec",
    "Dataset",
    "DatasetVersion",
    "SchemaContract",
    "SourceFile",
]
