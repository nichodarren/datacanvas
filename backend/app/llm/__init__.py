"""The LLM layer (§12).

Two places only, and this package serves both: Router (§12.3) and Narrator
(§12.5). It holds no registry and no executor — what a model returns is a
`Proposal`, and something else decides whether to run it.

Model ids are not the contract here; capabilities are, and `probe` is how a
candidate is measured against them (D-076).
"""

from app.llm.cascade import Cascade
from app.llm.contract import (
    Capabilities,
    LLMClient,
    LLMError,
    LLMRefused,
    LLMUnavailable,
    Message,
    Proposal,
    ProviderConfig,
    ToolCall,
    ToolSpec,
)
from app.llm.factory import Layer, cascade_for, client_for, layers
from app.llm.openai_compatible import OpenAICompatibleClient
from app.llm.probe import ProbeResult, probe

__all__ = [
    "Capabilities",
    "Cascade",
    "LLMClient",
    "LLMError",
    "LLMRefused",
    "LLMUnavailable",
    "Layer",
    "Message",
    "OpenAICompatibleClient",
    "ProbeResult",
    "Proposal",
    "ProviderConfig",
    "ToolCall",
    "ToolSpec",
    "cascade_for",
    "client_for",
    "layers",
    "probe",
]
