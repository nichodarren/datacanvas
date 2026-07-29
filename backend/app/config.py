"""Runtime configuration.

Secrets come from the environment only — never the repo, never a log, never an
error response (§13.8). ``.env.example`` lists the names and nothing else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import PrivacyMode


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
