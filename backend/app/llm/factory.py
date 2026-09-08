"""Settings in, clients out (D-076).

Every provider is a row rather than a class, because all four are OpenAI-shaped
and what separates them is a URL, a key and a model name. Adding a fifth is a
line in `_ENDPOINTS` plus two settings; it is not a file.

The capabilities declared here are **claims**, not measurements. `probe.py` is
what turns a claim into a fact, and it is the thing to run when a model id
changes — which it will, roughly twice a year (D-076).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from app.config import Settings
from app.llm.cascade import Cascade
from app.llm.contract import Capabilities, LLMClient, LLMRefused, ProviderConfig
from app.llm.openai_compatible import OpenAICompatibleClient

#: Base URLs, all OpenAI-shaped. Gemini and Ollama both offer this surface, and
#: using it costs their own extensions and buys one parser instead of four.
_ENDPOINTS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}

#: What each provider is expected to do. Claims until probed.
_CAPABILITIES: dict[str, Capabilities] = {
    "gemini": Capabilities(function_calling=True, structured_output=True, context_tokens=1_000_000),
    "groq": Capabilities(function_calling=True, structured_output=True, context_tokens=131_072),
    # The free router picks per request, so this is the floor it filters for
    # rather than a promise about any one model behind it.
    "openrouter": Capabilities(
        function_calling=True, structured_output=True, context_tokens=32_768
    ),
    # Qwen3 carries Ollama's native Tools capability. Structured output through
    # the OpenAI surface is less reliable locally, so it is not claimed.
    "ollama": Capabilities(function_calling=True, structured_output=False, context_tokens=32_768),
}


@dataclass(frozen=True, slots=True)
class Layer:
    """One configured rung of the cascade."""

    provider: str
    model: str
    api_key: str | None
    #: Which key of this provider's several. Becomes `groq#2` in the rung's
    #: identity, which is what lets a pin hold one account rather than one
    #: vendor-shaped guess at which of them answered.
    account: int = 1


def layers(settings: Settings, *, local_only: bool = False) -> tuple[Layer, ...]:
    """The rungs this deployment actually has, in the configured order.

    ``local_only`` is privacy mode `local` (§13.5), and it is not a preference
    that ranks cloud lower — it removes cloud entirely. A cascade that could
    fall through to a cloud provider under that mode would turn an outage into
    a policy breach, which is the one failure mode the mode exists to prevent.

    A provider named in `llm_cascade` with no key is **skipped, not refused**:
    a deployment that has one key should run on one provider rather than fail
    to start because the template lists four.
    """
    local = Layer(provider="ollama", model=settings.ollama_model, api_key=None)
    if local_only:
        return (local,)

    # **All of one provider's keys, then the next provider.** `llm_cascade` is
    # an order of preference between vendors, and exhausting the fastest one's
    # accounts before dropping to a slower vendor is what honours it. The
    # alternative — round-robin across vendors — spreads load and throws the
    # preference away.
    keys: dict[str, tuple[str, ...]] = {
        "gemini": _keys(
            settings.gemini_api_key, settings.gemini_api_key_2, settings.gemini_api_key_3
        ),
        "groq": _keys(settings.groq_api_key, settings.groq_api_key_2, settings.groq_api_key_3),
        "openrouter": _keys(
            settings.openrouter_api_key,
            settings.openrouter_api_key_2,
            settings.openrouter_api_key_3,
        ),
        # Local has no key and exactly one account.
        "ollama": (),
    }
    models: dict[str, str] = {
        "gemini": settings.gemini_model,
        "groq": settings.groq_model,
        "openrouter": settings.openrouter_model,
        "ollama": settings.ollama_model,
    }

    found: list[Layer] = []
    for name in (part.strip() for part in settings.llm_cascade.split(",")):
        if not name or name not in models:
            continue
        if name == "ollama":
            found.append(Layer(provider=name, model=models[name], api_key=None))
            continue
        for account, key in enumerate(keys[name], start=1):
            found.append(Layer(provider=name, model=models[name], api_key=key, account=account))
    return tuple(found) or (local,)


def _keys(*values: SecretStr | None) -> tuple[str, ...]:
    """The keys a provider actually has, in order, gaps closed.

    A deployment that fills in the first and the third gets two accounts
    numbered 1 and 2, not 1 and 3. The number is a position in the cascade
    rather than a label on a key, and leaving a hole in it would put a gap in
    the identities for no reason anybody could read later.
    """
    return tuple(
        value.get_secret_value()
        for value in values
        if value is not None and value.get_secret_value().strip()
    )


def client_for(layer: Layer, settings: Settings) -> LLMClient:
    """One client for one rung."""
    endpoint = _ENDPOINTS.get(layer.provider)
    if endpoint is None:
        raise LLMRefused(
            f"{layer.provider!r} is not a provider this build knows; "
            f"add it to `_ENDPOINTS` rather than to a call site"
        )
    timeout = settings.llm_timeout_seconds
    if layer.provider == "ollama":
        endpoint = settings.ollama_base_url.rstrip("/") + "/v1"
        # A cold load is minutes on a laptop and seconds thereafter, and it is
        # not a hang. Sharing the cloud timeout turned the first call of every
        # idle period into a failure.
        timeout = settings.llm_local_timeout_seconds

    return OpenAICompatibleClient(
        ProviderConfig(
            provider=layer.provider,
            base_url=endpoint,
            model=layer.model,
            api_key=layer.api_key,
            account=layer.account,
            # OpenRouter asks callers to identify themselves; it costs nothing
            # and it is what keeps a free-tier key from looking like abuse.
            headers=(
                {"X-Title": "DataCanvas", "HTTP-Referer": "https://datacanvas.local"}
                if layer.provider == "openrouter"
                else {}
            ),
            timeout_seconds=timeout,
        ),
        _CAPABILITIES.get(
            layer.provider,
            Capabilities(function_calling=False, structured_output=False, context_tokens=8_192),
        ),
    )


def cascade_for(settings: Settings, *, local_only: bool = False) -> Cascade:
    """The whole ladder, ready to call."""
    found = layers(settings, local_only=local_only)
    return Cascade(tuple(client_for(layer, settings) for layer in found))


__all__ = ["Layer", "cascade_for", "client_for", "layers"]
