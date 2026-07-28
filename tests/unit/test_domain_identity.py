"""Rules that live on the identity entities themselves (DESIGN.md §9.2, §13.2).

Every timestamp here is a fixed literal. A fixture whose meaning drifts with the
wall clock passes today and fails on some morning nobody planned for
(the project notes, working rules).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.domain import (
    SESSION_IDLE_TTL,
    InvariantViolation,
    Membership,
    Principal,
    Project,
    Role,
    Session,
    User,
    UserStatus,
    Workspace,
    WorkspacePolicy,
    normalize_email,
)
from app.domain.enums import PrivacyMode
from app.domain.errors import AuthorizationError
from app.domain.ids import (
    MembershipId,
    OrganizationId,
    ProjectId,
    SessionId,
    UserId,
    WorkspaceId,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
USER = UserId(UUID("00000000-0000-4000-8000-000000000001"))
OTHER_USER = UserId(UUID("00000000-0000-4000-8000-000000000002"))
WS_A = WorkspaceId(UUID("00000000-0000-4000-8000-00000000000a"))
WS_B = WorkspaceId(UUID("00000000-0000-4000-8000-00000000000b"))
SESSION = SessionId(UUID("00000000-0000-4000-8000-0000000000f1"))


def _session(**overrides: object) -> Session:
    defaults: dict[str, object] = {
        "id": SESSION,
        "user_id": USER,
        "token_hash": "a" * 64,
        "created_at": T0,
        "last_seen_at": T0,
        "expires_at": T0 + timedelta(days=30),
    }
    return Session(**{**defaults, **overrides})  # type: ignore[arg-type]


# ----------------------------------------------------------------- email ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rina@Example.COM", "rina@example.com"),
        ("  rina@example.com  ", "rina@example.com"),
        ("RINA@EXAMPLE.COM", "rina@example.com"),
    ],
)
def test_email_normalization_collapses_case_and_whitespace(raw: str, expected: str) -> None:
    """Without this, one person can hold two accounts and the unique index agrees."""
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "not-an-email"])
def test_email_normalization_rejects_nonsense(raw: str) -> None:
    with pytest.raises(InvariantViolation):
        normalize_email(raw)


def test_user_rejects_denormalized_email() -> None:
    """Storing an unnormalized address would defeat the lookup it feeds."""
    with pytest.raises(InvariantViolation):
        User(id=USER, email="Rina@Example.com", password_hash="x", created_at=T0)


def test_disabled_user_cannot_authenticate() -> None:
    user = User(
        id=USER,
        email="rina@example.com",
        password_hash="x",
        created_at=T0,
        status=UserStatus.DISABLED,
    )
    assert not user.can_authenticate


# --------------------------------------------------------------- session ----


def test_fresh_session_is_valid() -> None:
    assert _session().is_valid_at(T0 + timedelta(hours=1))


def test_session_expires_at_absolute_deadline() -> None:
    """30-day absolute expiry holds even for a session used constantly (§13.2)."""
    session = _session(expires_at=T0 + timedelta(days=30))
    still_active = T0 + timedelta(days=30)
    assert not session.is_valid_at(still_active, idle_ttl=timedelta(days=365))


def test_session_expires_after_idle_ttl() -> None:
    session = _session(last_seen_at=T0)
    assert session.is_valid_at(T0 + SESSION_IDLE_TTL - timedelta(seconds=1))
    assert not session.is_valid_at(T0 + SESSION_IDLE_TTL)


def test_revoked_session_is_invalid_even_before_expiry() -> None:
    """FR-A.2: revocation must take effect immediately, not at the next expiry."""
    session = _session(revoked_at=T0 + timedelta(minutes=1))
    assert not session.is_valid_at(T0 + timedelta(minutes=2))


def test_session_rejects_naive_datetimes() -> None:
    """A naive datetime here would raise TypeError inside the auth path."""
    with pytest.raises(InvariantViolation):
        _session(created_at=datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001


def test_session_rejects_naive_now() -> None:
    with pytest.raises(InvariantViolation):
        _session().is_valid_at(datetime(2026, 1, 2, 12, 0))  # noqa: DTZ001


# ------------------------------------------------------------------ role ----


def test_role_ordering_is_total_and_matches_the_document() -> None:
    assert Role.OWNER.at_least(Role.EDITOR)
    assert Role.OWNER.at_least(Role.VIEWER)
    assert Role.EDITOR.at_least(Role.VIEWER)
    assert not Role.VIEWER.at_least(Role.EDITOR)
    assert not Role.EDITOR.at_least(Role.OWNER)


def test_viewer_cannot_write() -> None:
    """FR-A.5: viewer reads and runs read-only tools; it never uploads or deletes."""
    assert not Role.VIEWER.can_write
    assert Role.EDITOR.can_write
    assert Role.OWNER.can_write


# ------------------------------------------------------------- principal ----


def _principal(**memberships: Role) -> Principal:
    mapping = {WS_A: memberships["a"]} if "a" in memberships else {}
    if "b" in memberships:
        mapping[WS_B] = memberships["b"]
    return Principal(user_id=USER, session_id=SESSION, memberships=mapping)


def test_principal_knows_only_its_own_workspaces() -> None:
    principal = _principal(a=Role.EDITOR)
    assert principal.is_member_of(WS_A)
    assert not principal.is_member_of(WS_B)
    assert principal.role_in(WS_B) is None


def test_require_role_allows_sufficient_role() -> None:
    principal = _principal(a=Role.OWNER)
    assert principal.require_role(WS_A, Role.EDITOR) is Role.OWNER


def test_require_role_rejects_insufficient_role() -> None:
    principal = _principal(a=Role.VIEWER)
    with pytest.raises(AuthorizationError):
        principal.require_role(WS_A, Role.EDITOR)


def test_require_role_rejects_non_membership_identically() -> None:
    """Non-member and under-privileged must be indistinguishable to the caller.

    Telling them apart tells an attacker whether the workspace exists — the leak
    §13.3.1 L2 exists to prevent.
    """
    non_member = _principal()
    under_privileged = _principal(a=Role.VIEWER)

    with pytest.raises(AuthorizationError) as absent:
        non_member.require_role(WS_A, Role.EDITOR)
    with pytest.raises(AuthorizationError) as insufficient:
        under_privileged.require_role(WS_A, Role.EDITOR)

    assert type(absent.value) is type(insufficient.value)


def test_principal_memberships_cannot_be_mutated_after_construction() -> None:
    """The mapping that decides who reads whose data must not be editable."""
    source = {WS_A: Role.VIEWER}
    principal = Principal(user_id=USER, session_id=SESSION, memberships=source)

    source[WS_B] = Role.OWNER  # mutating the original must not leak in
    assert not principal.is_member_of(WS_B)

    with pytest.raises(TypeError):
        principal.memberships[WS_B] = Role.OWNER  # type: ignore[index]


# ------------------------------------------------------- workspace/policy ----


def test_workspace_policy_defaults_to_balanced() -> None:
    """OQ-4 decided `balanced` as the default privacy mode (§13.5.2)."""
    assert WorkspacePolicy(workspace_id=WS_A).llm_privacy_mode is PrivacyMode.BALANCED


@pytest.mark.parametrize(
    "kwargs",
    [{"llm_monthly_token_budget": -1}, {"retention_versions": 0}],
)
def test_workspace_policy_rejects_impossible_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(InvariantViolation):
        WorkspacePolicy(workspace_id=WS_A, **kwargs)  # type: ignore[arg-type]


def test_workspace_requires_a_name() -> None:
    with pytest.raises(InvariantViolation):
        Workspace(
            id=WS_A,
            organization_id=OrganizationId(uuid4()),
            name="   ",
            created_at=T0,
            created_by=USER,
        )


def test_project_requires_a_name() -> None:
    with pytest.raises(InvariantViolation):
        Project(id=ProjectId(uuid4()), workspace_id=WS_A, name="", created_at=T0)


def test_membership_records_who_granted_it() -> None:
    """§13.7 audits role changes; the granting user must be recorded from day one."""
    membership = Membership(
        id=MembershipId(uuid4()),
        user_id=OTHER_USER,
        workspace_id=WS_A,
        role=Role.EDITOR,
        created_at=T0,
        invited_by=USER,
    )
    assert membership.invited_by == USER
