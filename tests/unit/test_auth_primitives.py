"""Password hashing, session tokens, log redaction (§13.2, §13.7.1, NFR-OBS).

Cheap argon2 parameters throughout: what is under test is the wrapper's
behaviour, not the KDF's difficulty.
"""

from __future__ import annotations

import pytest

from app.auth.passwords import (
    DUMMY_HASH,
    MIN_PASSWORD_LENGTH,
    OWASP_MEMORY_COST_KIB,
    OWASP_TIME_COST,
    PasswordHasher,
    WeakPassword,
)
from app.auth.tokens import TOKEN_BYTES, generate_token, hash_prompt, hash_token
from app.observability import REDACTED, redact
from app.repositories.audit import ALLOWED_METADATA_KEYS


@pytest.fixture(scope="module")
def hasher() -> PasswordHasher:
    return PasswordHasher(memory_cost=8, time_cost=1, parallelism=1)


# ------------------------------------------------------------- passwords ----


def test_hash_then_verify(hasher: PasswordHasher) -> None:
    stored = hasher.hash("correct-horse-battery")
    assert hasher.verify("correct-horse-battery", stored).ok


def test_wrong_password_fails(hasher: PasswordHasher) -> None:
    stored = hasher.hash("correct-horse-battery")
    assert not hasher.verify("correct-horse-stapler", stored).ok


def test_same_password_hashes_differently_each_time(hasher: PasswordHasher) -> None:
    """Salting. Two users with the same password must not share a hash."""
    assert hasher.hash("correct-horse-battery") != hasher.hash("correct-horse-battery")


def test_corrupt_hash_fails_without_raising(hasher: PasswordHasher) -> None:
    """A damaged row must not turn login into a 500.

    It also must not be distinguishable from a wrong password — that difference
    is information about the account.
    """
    assert not hasher.verify("anything", "not-an-argon2-hash").ok


@pytest.mark.parametrize("password", ["short", "a" * (MIN_PASSWORD_LENGTH - 1), ""])
def test_policy_rejects_short_passwords(hasher: PasswordHasher, password: str) -> None:
    with pytest.raises(WeakPassword):
        hasher.hash(password)


def test_policy_rejects_absurdly_long_passwords(hasher: PasswordHasher) -> None:
    """argon2 hashes the whole input, so an unbounded password is free server CPU."""
    with pytest.raises(WeakPassword):
        hasher.hash("a" * 5000)


def test_needs_rehash_when_parameters_were_raised() -> None:
    """Raising the cost later must not leave existing accounts behind."""
    weak = PasswordHasher(memory_cost=8, time_cost=1, parallelism=1)
    strong = PasswordHasher(memory_cost=64, time_cost=2, parallelism=1)

    old_hash = weak.hash("correct-horse-battery")
    result = strong.verify("correct-horse-battery", old_hash)
    assert result.ok
    assert result.needs_rehash


def test_default_parameters_meet_owasp() -> None:
    """A regression guard on the numbers themselves.

    They are easy to lower by accident while making tests faster, and nothing
    else would notice.
    """
    assert OWASP_MEMORY_COST_KIB >= 19456
    assert OWASP_TIME_COST >= 2


def test_dummy_hash_is_a_real_argon2_hash() -> None:
    """Login verifies against it when the account is unknown (§13.2).

    If it were not a valid hash, verification would fail early and the timing
    difference would be exactly the enumeration signal it exists to remove.
    """
    assert DUMMY_HASH.startswith("$argon2id$")
    assert not PasswordHasher().verify("dummy-password-for-timing-equalisation2", DUMMY_HASH).ok


# ---------------------------------------------------------------- tokens ----


def test_tokens_are_unique_and_long_enough() -> None:
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100
    # urlsafe base64 of 32 bytes, minus padding.
    assert all(len(token) >= TOKEN_BYTES for token in tokens)


def test_token_hash_is_stable_and_hex() -> None:
    token = generate_token()
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == 64
    int(hash_token(token), 16)  # raises if not hex


def test_different_tokens_hash_differently() -> None:
    assert hash_token(generate_token()) != hash_token(generate_token())


def test_prompt_hash_does_not_contain_the_prompt() -> None:
    """§13.7.1: the audit log stores a hash because it can never be deleted."""
    prompt = "why is Budi Santoso's amount 1.250.000?"
    digest = hash_prompt(prompt)
    assert "Budi" not in digest
    assert digest == hash_prompt(prompt)
    assert digest != hash_prompt(prompt + " ")


def test_column_names_are_not_an_allowed_audit_key() -> None:
    """A column name is already sensitive on its own (K1, §13.5.1).

    So the audit log records the contract id and the ordinal, and whoever needs
    the name resolves it from a table that can still be deleted.
    """
    assert "column_name" not in ALLOWED_METADATA_KEYS
    assert {"column_ordinal", "schema_contract_id"} <= ALLOWED_METADATA_KEYS


# -------------------------------------------------------------- redaction ----


@pytest.mark.parametrize(
    "key",
    ["password", "Password", "session_token", "api_key", "authorization", "cookie", "secret"],
)
def test_secret_shaped_keys_are_redacted(key: str) -> None:
    assert redact({key: "sensitive"})[key] == REDACTED


def test_redaction_recurses() -> None:
    cleaned = redact({"outer": {"password": "x", "safe": 1}})
    assert cleaned["outer"]["password"] == REDACTED
    assert cleaned["outer"]["safe"] == 1


def test_ordinary_fields_survive() -> None:
    assert redact({"workspace_id": "abc", "row_count": 5}) == {
        "workspace_id": "abc",
        "row_count": 5,
    }
