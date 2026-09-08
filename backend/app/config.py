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
        # Anchored, for exactly the reason written above `PROJECT_ROOT` — and
        # this line was the one place the reason had not been applied. A bare
        # `.env` resolves against the working directory, so `python -m app`
        # from the repository root read the file and `python -m app.llm` from
        # `backend/` read nothing: every key absent, every provider silently
        # dropped from the cascade, and a probe reporting that no model in the
        # world can route.
        env_file=PROJECT_ROOT / ".env",
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

    # **Model ids are expected to expire, and these defaults will.** v1 pinned
    # `gemini-2.5-flash` and it shuts down 16 October 2026, the second wave
    # after four Gemini 2.0 ids died on 1 June 2026. What is stable is the
    # capability contract in `app.llm.contract`, and `app.llm.probe` is what
    # measures a candidate against it (D-076). Treat every name below as a
    # value to re-check, not as a decision.
    #
    # **A key belongs to a provider, not to a position in the cascade.** The
    # first version of this named them `llm_api_key` / `llm_fallback_api_key`,
    # which meant reordering the cascade silently pointed one provider's key at
    # another provider's endpoint. Order lives in `llm_cascade` alone.
    # Two more keys per provider, from separate accounts (D-096). They are
    # not a fallback in the sense the cascade means — a second key behind the
    # same vendor shares its outage and its retirement schedule. What it does
    # not share is the **quota**, and a free tier's per-minute ceiling is what
    # ends a six-step turn halfway through.
    #
    # Absent keys are skipped rather than refused, so filling in one is a
    # deployment with one and filling in three is a deployment with three.
    gemini_api_key: SecretStr | None = None
    gemini_api_key_2: SecretStr | None = None
    gemini_api_key_3: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"

    groq_api_key: SecretStr | None = None
    groq_api_key_2: SecretStr | None = None
    groq_api_key_3: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"

    openrouter_api_key: SecretStr | None = None
    openrouter_api_key_2: SecretStr | None = None
    openrouter_api_key_3: SecretStr | None = None
    #: Not a model but a router: it picks a live free model that supports what
    #: the request needs, which is the answer to a pinned id that stops
    #: existing.
    openrouter_model: str = "openrouter/free"

    # Privacy mode `local` (§13.5). Qwen3 30B-A3B activates ~3B parameters of
    # 30B, so it answers at small-model speed with large-model reliability;
    # below 14B is fragile across the six steps §12.3 allows.
    ollama_base_url: str = "http://localhost:11434"
    # **Measured against the machine, not chosen from a table.** The pick was
    # `qwen3:30b-a3b` until the hardware was read: an 8 GB RTX 4060 Laptop with
    # 15.7 GB of system RAM, where an 18.6 GB download does not fit in either.
    # `qwen3:8b` at Q4_K_M is 5.2 GB and sits entirely in VRAM with room for
    # context. It probes clean, and the cost of being under 14B is real rather
    # than theoretical — see `llm_local_timeout_seconds`.
    ollama_model: str = "qwen3:8b"

    # **Its own timeout, because a local model has a cost no cloud one has:**
    # the weights are loaded from disk into VRAM on the first call after every
    # idle period. Probed on this machine, the first call **timed out at 61 s**,
    # the second answered in 27 s, and the third in 4.3 s. One shared 60 s
    # timeout therefore fails the first question a user ever asks in `local`
    # mode, which is the worst possible one to fail.
    llm_local_timeout_seconds: float = 300.0

    #: Cascade order, first to last. Providers with no key are skipped.
    #:
    #: **Groq leads on measurement, not on preference.** One turn is up to
    #: seven calls (MAX_STEPS = 6 plus the narration), so per-call latency is
    #: multiplied by seven before a user sees anything. Probed three times each
    #: on this machine: `gemini-3.5-flash` 6,393 ms median — **45 seconds a
    #: turn**, which is not a product — against `gemini-3.5-flash-lite` 916 ms
    #: and Groq `openai/gpt-oss-120b` 603 ms. All three called the tool
    #: correctly every time; only the clock separated them.
    #:
    #: They also fail differently, which is why this order and not a duplicate:
    #: Groq's free tier is tight on tokens (30k TPM) and generous on requests
    #: (14,400/day), Gemini's is the reverse (250k TPM, 10 RPM).
    llm_cascade: str = "groq,gemini,openrouter,ollama"

    # One turn is up to seven calls, so a generous per-call timeout is a turn
    # that hangs for minutes.
    llm_timeout_seconds: float = 60.0

    # §12.8. Unset means unmetered, which is the right default for a local
    # model and the wrong one for a paid key.
    llm_monthly_token_budget: int | None = None

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
