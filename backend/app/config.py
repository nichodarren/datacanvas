"""Runtime configuration.

Secrets come from the environment only — never the repo, never a log, never an
error response (§13.8). ``.env.example`` lists the names and nothing else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import PrivacyMode

#: The repository root, derived from this file's own location.
#:
#: Every path setting below defaults to something relative, and "relative"
#: previously meant *relative to the working directory* — which made the app's
#: behaviour depend on where somebody happened to stand when they started it.
#: Run from ``backend/``, the API booted normally and answered ``/health`` with
#: 200; the first sign of trouble was a user clicking a sample dataset and being
#: told it "is not installed on this server". A failure that waits for a user
#: action to appear is worse than one at startup, and this class of bug is the
#: one this project keeps writing down: correct because the caller happened to
#: be in the right place, not because anything said so.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment-backed settings. Grows per phase, like ``.env.example``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Phase 1: foundation & identity ---------------------------------
    database_url: str = "postgresql://datacanvas:datacanvas@localhost:5432/datacanvas"
    log_level: str = "INFO"

    # Reserved. Sessions are opaque random tokens stored hashed (§13.2), so
    # there is nothing to sign today. Kept because deployments already set it,
    # and because the first thing that does need signing should not have to
    # invent a new variable name.
    session_secret: SecretStr | None = None

    # --- Phase 2: storage ------------------------------------------------
    storage_backend: Literal["filesystem", "s3"] = "filesystem"
    storage_root: Path = Field(default=Path("./storage"))

    # Where FR-B.5's sample datasets are read from. Points at `eval/datasets`
    # by default because those files already exist and their SHA-256 is a
    # contract (golden_queries.md §3) — copying them into the package would
    # create a second copy that can drift, and the drifting one would be the
    # copy no check ever looks at.
    samples_root: Path = Field(default=Path("./eval/datasets"))

    @field_validator("storage_root", "samples_root")
    @classmethod
    def _anchor_to_repository(cls, value: Path) -> Path:
        """Resolve a relative path against the repository, never the cwd.

        An absolute value is returned untouched, so a deployment that sets
        ``STORAGE_ROOT=/var/lib/datacanvas`` still means exactly that. Only the
        relative defaults are anchored — and anchoring them is what makes
        ``python -m app`` behave the same from the repository root, from
        ``backend/``, or from anywhere else.
        """
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    # --- Phase 5: copilot ------------------------------------------------
    default_llm_privacy_mode: PrivacyMode = PrivacyMode.BALANCED

    @property
    def async_database_url(self) -> str:
        """The same URL with the async psycopg driver spelled out.

        SQLAlchemy picks its driver from the scheme, and a bare
        ``postgresql://`` resolves to the sync one. Deriving it here means
        ``DATABASE_URL`` stays a plain Postgres URL that psql, Alembic and any
        ops tool can also use.
        """
        url = self.database_url
        if url.startswith("postgresql+"):
            return url
        return url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings. Tests that need different values clear the cache."""
    return Settings()


__all__ = ["Settings", "get_settings"]
