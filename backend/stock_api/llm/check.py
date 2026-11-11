"""Check that the configured LLM answers and can call tools.

    python -m stock_api.llm.check            # plain reply + tool-calling test
    python -m stock_api.llm.check --no-tools # plain reply only

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ..config import Settings
from . import LLMConfigError, LLMError, build_gateway

QUOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_quote",
        "description": "Latest price and daily change for a NASDAQ-listed stock.",
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"}},
            "required": ["symbol"],
        },
    },
}


async def run(with_tools: bool) -> int:
    settings = Settings()
    try:
        gateway = build_gateway(settings)
    except LLMConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1

    primary = gateway.primary
    print(f"primary:  {primary.label} at {primary.base_url}")
    if gateway.fallback:
        print(f"fallback: {gateway.fallback.label} at {gateway.fallback.base_url}")

    ok = True
    try:
        reply = await gateway.chat(
            [{"role": "user", "content": "Reply with exactly one word: ready"}],
            temperature=0,
        )
        print(
            f"\n[1] plain reply via {reply.provider}/{reply.model} in {reply.latency_ms} ms: "
            f"{reply.content[:200]!r}"
        )
        print(f"    tokens in/out: {reply.usage.prompt_tokens}/{reply.usage.completion_tokens}")
    except LLMError as exc:
        print(f"\n[1] FAILED: {exc}")
        return 1

    if with_tools:
        try:
            result = await gateway.chat(
                [
                    {"role": "system", "content": "Use the tools to answer stock questions."},
                    {"role": "user", "content": "What is Apple's (AAPL) stock price right now?"},
                ],
                tools=[QUOTE_TOOL],
                temperature=0,
            )
        except LLMError as exc:
            print(f"\n[2] FAILED: {exc}")
            return 1
        calls = [c for c in result.tool_calls if c.name == "get_quote"]
        symbol = str(calls[0].arguments.get("symbol", "")).upper() if calls else ""
        if symbol == "AAPL":
            print(
                f"\n[2] tool calling OK via {result.provider}/{result.model}: "
                f"get_quote({json.dumps(calls[0].arguments)})"
            )
        else:
            ok = False
            print(
                f"\n[2] tool calling NOT OK: expected get_quote(symbol=AAPL), got "
                f"{[(c.name, c.arguments) for c in result.tool_calls]} "
                f"content={result.content[:200]!r}"
            )
            print("    Use a model with native tool support, e.g. qwen3:8b or llama3.1:8b.")

    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-tools", action="store_true", help="skip the tool-calling test")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(run(with_tools=not args.no_tools)))


if __name__ == "__main__":
    main()
