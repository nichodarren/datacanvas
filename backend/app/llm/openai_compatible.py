"""One client for every provider this build speaks to.

## Why there is one adapter and not four

Gemini, Groq, OpenRouter and Ollama all expose an OpenAI-shaped
`/chat/completions`, so what actually separates them is a URL, a key and a
model name — three values, not three code paths. Four adapters would be four
places to keep a tool-call parser correct, and they would drift in the way only
code nobody reads drifts: silently, and only for the provider nobody tests.

| Provider | Base URL |
|---|---|
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Groq | `https://api.groq.com/openai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama | `http://localhost:11434/v1` |

The cost is that a provider's own extensions are unreachable. That is accepted:
§12.3 needs a tool call and some text, and anything a single vendor offers on
top of that is a dependency on a vendor whose model ids expire twice a year
(D-076).

## What this file refuses to do

It does not retry, and it does not fall back — `cascade.py` owns both, because
a client that silently retried would make the token budget in §12.8 count
something other than what was spent. It does not execute anything. And it never
puts a request body or a header into an exception, because the key is in a
header and exceptions get logged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.contract import (
    Capabilities,
    LLMRefused,
    LLMUnavailable,
    Message,
    Proposal,
    ProviderConfig,
    ToolCall,
    ToolSpec,
)

#: Statuses worth trying the next provider for. Everything else is a decision
#: the provider made about this request, and it would make it again.
_RETRYABLE = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class OpenAICompatibleClient:
    """A model behind an OpenAI-shaped chat completions endpoint."""

    def __init__(
        self,
        config: ProviderConfig,
        capabilities: Capabilities,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = config.provider
        # `groq` when there is one account, `groq#2` when there are several.
        # The plain name still drives endpoints and capabilities; this names
        # the *rung*, which is what a pin has to be able to hold on to.
        self.identity = (
            config.provider if config.account <= 1 else f"{config.provider}#{config.account}"
        )
        self.model = config.model
        self.capabilities = capabilities
        self._config = config
        # Injected in tests so no test can reach the network by forgetting to
        # patch something. In production one client per provider keeps the
        # connection pool warm, which matters when a turn is seven calls.
        self._client = client
        self._owned = client is None

    async def aclose(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json", **self._config.headers}
            if self._config.api_key:
                headers["Authorization"] = f"Bearer {self._config.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url.rstrip("/"),
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        return self._client

    def pin(self, provider: str) -> OpenAICompatibleClient:
        """Itself. One client is one model; there is nothing to narrow."""
        return self

    async def propose(
        self,
        messages: tuple[Message, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> Proposal:
        if tools and not self.capabilities.function_calling:
            # Refused rather than sent-and-hoped. A model without tool calling
            # answers a Router prompt with prose that looks like an answer, and
            # §12.3 step 6 would reject it every time without ever saying why.
            raise LLMRefused(f"{self.provider}/{self.model} was given tools and does not call them")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_wire_message(message) for message in messages],
            # Zero by default, and that is INV-6 leaking upward: the same
            # question should propose the same Step. It is not a guarantee —
            # no provider offers one — but a temperature nobody set is a
            # different answer every time by design.
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        if tools:
            payload["tools"] = [_wire_tool(spec) for spec in tools]
            payload["tool_choice"] = "auto"

        try:
            response = await self._http().post("/chat/completions", json=payload)
        except httpx.TimeoutException as cause:
            raise LLMUnavailable(f"{self.identity} timed out") from cause
        except httpx.HTTPError as cause:
            # `str(cause)` on an httpx error is a URL, and a base URL can carry
            # a key on some gateways. The class name is enough to act on.
            raise LLMUnavailable(f"{self.identity} unreachable ({type(cause).__name__})") from cause

        if response.status_code == 429:
            # Named rather than numbered. P6 asks that a failure be written to
            # be read by a person, and on a free tier this is the one they will
            # meet most: `groq answered 429` tells a reader nothing they can act
            # on, and *wait a moment* is the entire remedy.
            #
            # And the provider says how long that moment is, so the wait is
            # carried rather than guessed at.
            raise LLMUnavailable(
                f"{self.identity} is rate limiting this key right now; "
                f"the free tier allows a few turns a minute",
                retry_after=_retry_after(response),
            )
        if response.status_code in _RETRYABLE:
            raise LLMUnavailable(f"{self.identity} answered {response.status_code}")
        if response.status_code >= 400:
            raise LLMRefused(
                f"{self.identity} rejected the request ({response.status_code}): "
                f"{_reason(response)}"
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError as cause:
            raise LLMUnavailable(
                f"{self.identity} answered with something that is not JSON"
            ) from cause

        return self._read(body)

    def _read(self, body: dict[str, Any]) -> Proposal:
        choices = body.get("choices") or []
        message: dict[str, Any] = choices[0].get("message", {}) if choices else {}
        usage: dict[str, Any] = body.get("usage") or {}

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            written = function.get("arguments") or "{}"
            parsed: dict[str, Any] = {}
            unparsed: str | None = None
            try:
                loaded = json.loads(written)
                # A JSON scalar is valid JSON and not a set of arguments, so it
                # goes down the same path as broken syntax: §12.3 step 6 needs
                # to tell the model what it actually sent.
                if isinstance(loaded, dict):
                    parsed = loaded
                else:
                    unparsed = written
            except ValueError:
                unparsed = written
            extra = raw.get("extra_content")
            calls.append(
                ToolCall(
                    id=str(raw.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=parsed,
                    unparsed=unparsed,
                    extra=extra if isinstance(extra, dict) else None,
                )
            )

        content = message.get("content")
        return Proposal(
            text=content if isinstance(content, str) and content.strip() else None,
            calls=tuple(calls),
            model=str(body.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            provider=self.identity,
        )


def _wire_message(message: Message) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        # Sent back in the shape it arrived in, arguments included: a provider
        # replaying the turn matches the `tool` message to this by id, and one
        # without a `function.name` is what Groq refuses outright.
        #
        # ⚠️ **`extra_content` included, and the sentence above used to be
        # false without it.** Gemini hangs a `thought_signature` there and
        # answers the next call with `400 Function call is missing a
        # thought_signature`, so dropping it made Gemini a one-step provider —
        # invisible while the cascade always picked Groq, and fatal the moment
        # it was asked to go first, because every chart takes two steps.
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                **({"extra_content": call.extra} if call.extra else {}),
            }
            for call in message.tool_calls
        ]
        wire["content"] = message.content or None
    return wire


def _wire_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _reason(response: httpx.Response) -> str:
    """The provider's own words, truncated, never the request.

    Providers disagree about where the message lives, and a 400 whose reason is
    unreadable is a deployment somebody has to guess at.
    """
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:200]
        if error is not None:
            return str(error)[:200]
    return str(body)[:200]


def _retry_after(response: httpx.Response) -> float | None:
    """How long the provider asked us to wait, in seconds.

    `Retry-After` is defined as either a number of seconds or an HTTP date.
    Only the number is read: the date form needs a clock agreeing with the
    server's, and a wait computed from a skewed clock is worse than no wait.
    Groq sends seconds, and fractional ones.

    Anything unparseable, negative, or absent yields `None`, which the cascade
    reads as *do not wait* — failing promptly beats sleeping on a guess.
    """
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


__all__ = ["OpenAICompatibleClient"]
