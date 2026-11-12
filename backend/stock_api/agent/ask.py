"""Ask the agent a question from the terminal and watch the tool calls.

python -m stock_api.agent.ask "What is NVIDIA's latest price?"
python -m stock_api.agent.ask --detailed "Compare AAPL and MSFT over 6 months"
python -m stock_api.agent.ask --conversation <id> "and its volume?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ..config import get_settings
from ..llm import LLMConfigError
from .factory import create_agent


async def ask(question: str, mode: str, conversation_id: str | None) -> int:
    try:
        agent = create_agent(get_settings())
    except LLMConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1

    current_step = 0
    exit_code = 0
    async for event in agent.run(
        question,
        mode="detailed" if mode == "detailed" else "simple",
        conversation_id=conversation_id,
    ):
        data = event.data
        if event.type == "conversation":
            print(f"conversation: {data['conversation_id']} ({data['mode']})")
        elif event.type == "status":
            current_step = data["step"]
            print(f"\n[step {current_step}] thinking...", flush=True)
        elif event.type == "token":
            print(data["text"], end="", flush=True)
        elif event.type == "tool_call":
            print(f"\n  -> {data['name']}({json.dumps(data['arguments'])})", flush=True)
        elif event.type == "tool_result":
            status = "ok" if data["ok"] else f"error: {data['error']}"
            print(f"  <- {data['name']} {status} ({data['latency_ms']} ms)", flush=True)
        elif event.type == "sources":
            for source in data["sources"]:
                print(f"\nsource: {source['source']} (as of {source['as_of']})")
        elif event.type == "done":
            usage = data["usage"]
            print(
                f"\nmodels: {', '.join(usage['models'])}  llm calls: {usage['llm_calls']}  "
                f"tool calls: {usage['tool_calls']}  tokens: "
                f"{usage['prompt_tokens']}/{usage['completion_tokens']}"
            )
            print(f"disclaimer: {data['disclaimer']}")
        elif event.type == "error":
            print(f"\nERROR ({data['code']}): {data['message']}")
            exit_code = 1
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the stock research agent a question.")
    parser.add_argument("question")
    parser.add_argument("--detailed", action="store_true", help="detailed explanation mode")
    parser.add_argument("--conversation", help="continue an earlier conversation id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    sys.exit(
        asyncio.run(
            ask(args.question, "detailed" if args.detailed else "simple", args.conversation)
        )
    )


if __name__ == "__main__":
    main()
