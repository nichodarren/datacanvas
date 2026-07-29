"""The wire vocabulary and the domain vocabulary must agree.

``schemas.py`` spells its literals out instead of deriving them from the enums,
deliberately: the wire format should not shift because somebody renames a Python
member. The cost of that choice is drift, and this is where the cost is paid —
mechanically, rather than by whoever next reads both files.

Without it the failure is quiet in the worst way. A logical type added to §9.2
and forgotten here is a type the detector can produce and the API cannot accept
back, so the column becomes uncorrectable (FR-C.2) with no error anywhere.
"""

from __future__ import annotations

import typing

from app.api import schemas
from app.domain.enums import ColumnRole, LogicalType, Role


def test_the_logical_types_on_the_wire_are_the_ones_in_the_domain() -> None:
    assert set(typing.get_args(schemas.LogicalTypeName)) == {t.value for t in LogicalType}


def test_the_column_roles_on_the_wire_are_the_ones_in_the_domain() -> None:
    assert set(typing.get_args(schemas.ColumnRoleName)) == {r.value for r in ColumnRole}


def test_the_membership_roles_on_the_wire_are_the_ones_in_the_domain() -> None:
    """The same guard for the literal that was already there, unguarded."""
    annotation = schemas.AddMemberRequest.model_fields["role"].annotation
    assert set(typing.get_args(annotation)) == {role.value for role in Role}
