"""What the copilot may ask of a model, and what a model may answer (§12.1).

## The model never executes, and this file is where that is made true

§12.1 puts the LLM in exactly two places — Router and Narrator — and states the
boundary as *"it returns a proposal; the Step Executor runs it after
validation"*. A client that could run a tool would make that boundary a promise
in a prompt, and §12.1 is explicit that **prompt is preference, code is
guarantee**. So the only thing a client here can return is a `Proposal`: text,
or names and arguments. It has no reference to the registry, no executor, and
nothing to call.

## Why the model name is not the contract

v1 pinned `gemini-2.5-flash` in `.env` and that model shuts down on 16 October
2026, the second wave after four Gemini 2.0 ids died on 1 June 2026. Mandatory
migration every four or five months is the pattern, so **a name in a config
file is a fact with an expiry date**, and building on one guarantees this
session repeats.

What is stable is what §12.3 actually needs, and it is narrower than *a good
chat model*: the Router returns a tool call whose arguments are validated
against a schema and rejected up to twice with feedback. A model without
reliable function calling fails at step 6 forever, whatever it scores at chat.
So `Capabilities` is the contract, `probe.py` is how a candidate is measured
against it, and §12.9's golden queries are the gate that decides whether it may
be the default (D-076).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.domain.errors import DomainError

Role = Literal["system", "user", "assistant", "tool"]


class LLMError(DomainError):
    """A model could not be reached or would not answer.

    Carries no request body and no headers on purpose: an API key lives in a
    header, and an exception is the object most likely to be logged, attached
    to an audit row, or shown in a stack trace.
    """


class LLMUnavailable(LLMError):
    """Transport, timeout, rate limit, or the provider itself is down.

    The cascade moves to the next provider on this and only this. A refusal
    that would repeat identically at the next provider is not this.

    ``retry_after`` is the provider's own answer to *when should I come back*,
    in seconds, when it gave one. A rate limit is the one failure in this class
    that **fixes itself**, and the provider knows exactly when — so throwing a
    turn away instead of waiting the six seconds it asked for discards work
    that already ran.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMRefused(LLMError):
    """The provider answered, and the answer was no.

    Bad key, model not found, request rejected. Falling through to the next
    provider would hide a misconfiguration behind a working fallback, which is
    how a deployment ends up permanently on its third choice without anybody
    knowing.
    """


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a model must be able to do before it is allowed to be the Router.

    Checked at construction rather than at call time. A model that cannot call
    tools fails every turn in the same way, and discovering that on a user's
    first question is worse than refusing to start.
    """

    #: §12.3 step 5. Without it there is no Router, only a Narrator.
    function_calling: bool
    #: JSON that conforms to a supplied schema. Weaker models offer the first
    #: and not the second; the planner survives that, so it is not required.
    structured_output: bool
    #: §12.4 assembles structured session state rather than a transcript, so
    #: this is smaller than it would otherwise be. It is still a floor.
    context_tokens: int


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool as the model is allowed to see it (§11.2).

    ``parameters`` is JSON Schema and is **generated from the tool's own
    declaration**, never written twice. §11.2 makes one definition produce the
    runtime validation, the manual form, this, and the documentation — two
    hand-written copies of one schema is two things that must agree, and only
    one of them is the one that runs.

    Tier 3 arguments never appear here (D-019): `plot.transform` reaches into
    Vega-Lite's `aggregate`/`bin`/`calculate`, and a model that could set it
    would be computing numbers outside a Computation, which is INV-5.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A proposal to run one tool. **Not a run.**"""

    id: str
    name: str
    arguments: dict[str, Any]
    #: The model's own text when its arguments were not valid JSON at all.
    #:
    #: Kept rather than raised, because §12.3 step 6 rejects a bad proposal
    #: **with feedback** and retries twice. Turning it into an exception here
    #: would remove the one thing that turn needs to recover: what the model
    #: actually said.
    unparsed: str | None = None
    #: Whatever the provider hung off this call that is not part of the
    #: OpenAI shape, carried back untouched.
    #:
    #: **Opaque on purpose.** Gemini returns a `thought_signature` in here and
    #: rejects the *next* call with `400 Function call is missing a
    #: thought_signature` if it does not come back — which made Gemini a
    #: one-step provider for as long as this field was dropped, and every chart
    #: now takes two steps. Reading the contents would tie this adapter to one
    #: vendor's reasoning format; echoing them ties it to nothing.
    #:
    #: Never reaches a tool: it is transport, so it is not an argument and it
    #: is not in the §9.4 fingerprint.
    extra: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of the conversation as the provider sees it.

    Not what the user sees, and not stored: §12.4 keeps structured session
    state and assembles this per call. A transcript would grow without bound
    and would carry raw values past the Privacy Gate by accident.
    """

    role: Role
    content: str
    #: Set only on a `tool` message, tying a result back to the call that asked
    #: for it. Providers reject a tool message without one.
    tool_call_id: str | None = None
    #: Set only on an `assistant` message that **made** those calls.
    #:
    #: Not decoration, and not optional in practice: a `tool` message answers a
    #: call, so the call has to be in the conversation for the answer to attach
    #: to. Replaying the turn as *assistant said "calling profile_column"* and
    #: then a tool result was accepted by some providers and rejected outright
    #: by Groq's harmony renderer — `Tools should have a name!` — which is the
    #: better behaviour: the transcript really was malformed everywhere, and
    #: only one provider said so.
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Proposal:
    """Everything one model call produced.

    Both fields can be filled at once, and that is not a defect: a model may
    narrate and call a tool in the same breath.
    """

    text: str | None = None
    calls: tuple[ToolCall, ...] = ()
    #: Which model answered. The cascade means it is not always the one asked,
    #: and §12.8 cost accounting needs to know which one it paid for.
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    #: Which rung answered — `groq`, or `groq#2` when several accounts of one
    #: provider are configured. A **rung identity** rather than a bare provider
    #: name, because `pin` has to be able to name the one that replied and two
    #: accounts of one vendor would otherwise be indistinguishable.
    #:
    #: Not a URL: the URL carries a key in some deployments and this value is
    #: written to audit rows.
    provider: str = ""

    @property
    def spent(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    """One model, reachable.

    Deliberately one method. A client that also embedded, also streamed and
    also counted tokens would be four reasons to change one file, and §12.2's
    stage 1 needs exactly this call with a tiny payload.
    """

    #: Read-only, and declared as properties for that reason: which provider
    #: answered is a fact about a client, not a dial on it. A settable
    #: attribute here would also refuse `Cascade`, whose three are derived.
    @property
    def provider(self) -> str: ...

    @property
    def identity(self) -> str:
        """Which **rung**, not which vendor: `groq`, or `groq#2`.

        Two accounts of one provider share a name and are different keys, and
        `pin` has to be able to say which one answered. Equal to `provider`
        wherever a deployment has one account, which is most of them.
        """
        ...

    @property
    def model(self) -> str: ...

    @property
    def capabilities(self) -> Capabilities: ...

    async def propose(
        self,
        messages: tuple[Message, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> Proposal:
        """Ask once. Never retries, never falls back, never executes."""
        ...

    def pin(self, identity: str) -> LLMClient:
        """What answers the rest of this conversation, given who answered first.

        **A conversation belongs to one model.** Falling through mid-turn means
        replaying another vendor's tool-call transcript at a vendor that
        validates it differently, and they do: Gemini refuses a `functionCall`
        without its own `thought_signature`, and Groq refuses an assistant turn
        whose calls have no name. Both refusals are correct — the transcript
        really is not theirs.

        So a cascade is the right shape **between** turns and the wrong one
        **within** one. Found by the product owner asking a question that took
        three calls, the first two answered by Groq and the third falling to
        Gemini, which refused the history it was handed.
        """
        ...


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Where a provider lives and what to call it.

    ``base_url`` is here rather than hard-coded per class because all four
    providers this build speaks to are OpenAI-shaped, including Gemini and
    Ollama, so what separates them **is** the URL, the key and the model name.
    One adapter and four rows beats four adapters that drift.
    """

    provider: str
    base_url: str
    model: str
    api_key: str | None = None
    #: Which key of this provider's several. 1 is the only one most
    #: deployments have; 2 and 3 are separate accounts, which raise the
    #: ceiling a free tier puts on a turn without adding a vendor.
    account: int = 1
    #: Sent as-is. Some gateways want attribution headers.
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 60.0


__all__ = [
    "Capabilities",
    "LLMClient",
    "LLMError",
    "LLMRefused",
    "LLMUnavailable",
    "Message",
    "Proposal",
    "ProviderConfig",
    "Role",
    "ToolCall",
    "ToolSpec",
]
