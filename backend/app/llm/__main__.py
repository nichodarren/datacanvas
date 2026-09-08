"""`python -m app.llm` — ask every configured provider to prove it can route.

The thing to run when a model id changes, which it will roughly twice a year
(D-076). It answers one question per provider: *would this model be able to be
the Router at all?* Quality is not measured here; §12.9's golden queries do
that, and they are the gate for choosing a default.

Nothing here writes, nothing here is cached, and no key is printed.
"""

# ruff: noqa: T201 — this module *is* the report. Its output is the product,
# and routing it through `logging` would put a probe table behind a log level.
from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.llm.contract import LLMError
from app.llm.factory import client_for, layers
from app.llm.openai_compatible import OpenAICompatibleClient
from app.llm.probe import ProbeResult, probe


async def _run() -> list[ProbeResult]:
    settings = get_settings()
    found = layers(settings)
    results: list[ProbeResult] = []
    for layer in found:
        client = client_for(layer, settings)
        try:
            results.append(await probe(client))
        finally:
            if isinstance(client, OpenAICompatibleClient):
                await client.aclose()
    return results


def main() -> int:
    try:
        results = asyncio.run(_run())
    except LLMError as cause:
        print(f"could not build a cascade: {cause}", file=sys.stderr)
        return 2

    print(f"{'':6}{'provider':<12} {'model':<34} {'latency':>9} {'tokens':>9}  detail")
    print("-" * 110)
    for result in results:
        print(result.line())

    eligible = [result for result in results if result.eligible]
    print()
    print(f"{len(eligible)} of {len(results)} providers can route.")
    if not eligible:
        print(
            "None can. The copilot has no Router until one does; see D-076.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
