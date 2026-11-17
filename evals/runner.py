"""Runs the golden cases through the real agent, on the frozen snapshot, and scores them."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from financial_mcp import services as mcp_services
from financial_mcp.server import mcp as financial_mcp_server
from financial_mcp.services import set_services
from stock_api.agent import Agent, MCPToolbox, MemoryConversationStore, ToolPolicy
from stock_api.config import Settings
from stock_api.llm import LLMGateway

from .golden import Case, resolve, source_family
from .scoring import CaseResult, score_case
from .snapshot import SNAPSHOT_DAY, snapshot_services

logger = logging.getLogger("evals")


def build_agent(gateway: LLMGateway, settings: Settings) -> Agent:
    """The production agent with the snapshot tools served in-process.

    Background-job tools and approvals are left out: the eval measures answers, and an
    approval card has nobody to click it here.
    """
    return Agent(
        gateway,
        lambda: MCPToolbox.connect(financial_mcp_server, timeout=settings.mcp_call_timeout),
        MemoryConversationStore(),
        policy=ToolPolicy(max_tool_calls=settings.agent_max_tool_calls),
        max_steps=settings.agent_max_steps,
        tool_result_max_chars=settings.agent_tool_result_max_chars,
        history_messages=settings.agent_history_messages,
        today=lambda: SNAPSHOT_DAY,
    )


async def run_case(agent: Agent, case: Case, timeout: float) -> CaseResult:
    done: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = []
    error: str | None = None
    started = time.perf_counter()

    async def consume() -> None:
        nonlocal done, sources, error
        async for event in agent.run(case.question, mode="simple"):
            if event.type == "done":
                done = event.data
            elif event.type == "sources":
                sources = list(event.data.get("sources", []))
            elif event.type == "error":
                error = str(event.data.get("message"))

    try:
        await asyncio.wait_for(consume(), timeout)
    except TimeoutError:
        error = f"no answer within {timeout:.0f} seconds"
    except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
        error = f"{type(exc).__name__}: {exc}"
    result = score_case(case, done, sources)
    result.error = error or result.error
    result.seconds = round(time.perf_counter() - started, 2)
    return result


async def run_cases(
    agent: Agent,
    cases: list[Case],
    *,
    timeout: float = 300.0,
    delay: float = 0.0,
    on_result: Callable[[CaseResult], None] | None = None,
) -> list[CaseResult]:
    previous = mcp_services._services
    set_services(snapshot_services())
    results: list[CaseResult] = []
    try:
        for index, case in enumerate(cases):
            if index and delay:
                await asyncio.sleep(delay)
            result = await run_case(agent, case, timeout)
            results.append(result)
            if on_result is not None:
                on_result(result)
    finally:
        set_services(previous)
    return results


# --- expected values ----------------------------------------------------------------------


async def compute_expected(cases: list[Case]) -> dict[str, dict[str, Any]]:
    """Each case's figure values and source families, read from the snapshot tools."""
    previous = mcp_services._services
    set_services(snapshot_services())
    cache: dict[str, Any] = {}

    async def payload(tool: str, args: dict[str, Any]) -> Any:
        key = json.dumps([tool, args], sort_keys=True)
        if key not in cache:
            result = await financial_mcp_server.call_tool(tool, args)
            cache[key] = getattr(result, "structured_content", None)
        return cache[key]

    out: dict[str, dict[str, Any]] = {}
    try:
        for case in cases:
            values = [
                resolve(await payload(f.source.tool, f.source.args), f.source.path, f.source.reduce)
                for f in case.figures
            ]
            families: list[str] = []
            for call in case.oracle_calls():
                body = await payload(call.tool, call.args)
                family = source_family(body.get("source") if isinstance(body, dict) else None)
                if family and family not in families:
                    families.append(family)
            out[case.id] = {"values": values, "sources": families}
    finally:
        set_services(previous)
    return out
