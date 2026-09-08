"""Measure a model against the contract instead of trusting its name (D-076).

## Why this exists at all

The requirement in §12.3 is narrow and it is not *a good chat model*: the Router
returns a tool call whose arguments are validated against a schema and rejected
up to twice with feedback. A model that will not call a tool, or that calls one
with the argument names invented, fails **every** turn in the same way — and it
fails at step 6, where the only symptom a user sees is that nothing happened.

So this asks the model to do the one thing, once, and reports what came back.
It is deliberately not a benchmark: it does not score quality, and passing it
does not make a model the default. §12.9's golden queries decide that. This
decides whether a model is even eligible to be tried.

## What the task is, and why it is this one

One tool, two required arguments of different types, and a sentence that names
both values. Anything less checks that a model can emit *a* call; this checks
that it can emit the *right* one, which is what step 6 validates. The values are
picked so a wrong answer cannot be a lucky guess: a model that echoes the
schema's example, hallucinates argument names, or answers in prose all fail
distinguishably rather than all failing as "no".
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.llm.contract import (
    LLMClient,
    LLMError,
    Message,
    ToolSpec,
)

PROBE_TOOL = ToolSpec(
    name="record_reading",
    description="Record one temperature reading for one city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "The city the reading is from."},
            "celsius": {"type": "number", "description": "The temperature in degrees celsius."},
        },
        "required": ["city", "celsius"],
        "additionalProperties": False,
    },
)

PROBE_MESSAGES = (
    Message(
        role="system",
        content=(
            "You call tools. When a tool fits the request, call it and do not "
            "explain. Never answer in prose what a tool can answer."
        ),
    ),
    Message(role="user", content="Record a reading of 21 degrees celsius for Jakarta."),
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What one model did when asked to call one tool."""

    provider: str
    model: str
    reachable: bool
    #: It returned a tool call rather than prose.
    calls_tools: bool
    #: The call named the right tool, parsed as JSON, and carried both required
    #: arguments with the right types and the values from the sentence.
    obeys_schema: bool
    latency_ms: int
    tokens: int
    #: Human-readable, and safe to log: no request body, no headers, no key.
    detail: str

    @property
    def eligible(self) -> bool:
        """Whether this model may be a Router at all (§12.3)."""
        return self.reachable and self.calls_tools and self.obeys_schema

    def line(self) -> str:
        mark = "PASS" if self.eligible else "FAIL"
        return (
            f"{mark}  {self.provider:<12} {self.model:<34} "
            f"{self.latency_ms:>6} ms  {self.tokens:>5} tok  {self.detail}"
        )


async def probe(client: LLMClient) -> ProbeResult:
    """Ask once, judge the answer, never raise."""
    started = time.perf_counter()
    try:
        proposal = await client.propose(PROBE_MESSAGES, (PROBE_TOOL,), max_output_tokens=256)
    except LLMError as cause:
        return ProbeResult(
            provider=client.provider,
            model=client.model,
            reachable=False,
            calls_tools=False,
            obeys_schema=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens=0,
            detail=str(cause),
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    if not proposal.calls:
        return ProbeResult(
            provider=client.provider,
            model=proposal.model or client.model,
            reachable=True,
            calls_tools=False,
            obeys_schema=False,
            latency_ms=elapsed,
            tokens=proposal.spent,
            detail="answered in prose; no tool call",
        )

    call = proposal.calls[0]
    detail, obeys = _judge(call.name, call.arguments, call.unparsed)
    return ProbeResult(
        provider=client.provider,
        model=proposal.model or client.model,
        reachable=True,
        calls_tools=True,
        obeys_schema=obeys,
        latency_ms=elapsed,
        tokens=proposal.spent,
        detail=detail,
    )


def _judge(name: str, arguments: dict[str, object], unparsed: str | None) -> tuple[str, bool]:
    if unparsed is not None:
        return (f"arguments were not a JSON object: {unparsed[:80]}", False)
    if name != PROBE_TOOL.name:
        return (f"called {name!r}, not {PROBE_TOOL.name!r}", False)

    missing = [key for key in ("city", "celsius") if key not in arguments]
    if missing:
        return (f"missing {', '.join(missing)}; sent {sorted(arguments)}", False)

    city = arguments["city"]
    celsius = arguments["celsius"]
    if not isinstance(city, str) or city.strip().lower() != "jakarta":
        return (f"city came back as {city!r}", False)
    # `21` and `21.0` are the same reading. `bool` is excluded because
    # `isinstance(True, int)` is true in Python and `celsius=True` is not a
    # temperature.
    if isinstance(celsius, bool) or not isinstance(celsius, int | float):
        return (f"celsius came back as {celsius!r}", False)
    if abs(float(celsius) - 21.0) > 0.001:
        return (f"celsius came back as {celsius!r}", False)

    return ("called the tool with both arguments correct", True)


__all__ = ["PROBE_MESSAGES", "PROBE_TOOL", "ProbeResult", "probe"]
