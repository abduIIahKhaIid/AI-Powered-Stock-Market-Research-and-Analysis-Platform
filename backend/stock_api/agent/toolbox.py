"""Tools for the agent, served by MCP servers (SCRUM-62).

One MCP client session is opened per chat turn and closed when the turn ends.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp import Client

from ..llm import mcp_tool_to_openai


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_openai(self) -> dict[str, Any]:
        return mcp_tool_to_openai(self.name, self.description, self.input_schema)


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    arguments: dict[str, Any]
    ok: bool
    payload: Any = None
    error: str | None = None
    latency_ms: int = 0

    @property
    def source(self) -> str | None:
        if isinstance(self.payload, dict) and isinstance(self.payload.get("source"), str):
            return self.payload["source"]
        return None

    @property
    def as_of(self) -> str | None:
        if isinstance(self.payload, dict) and self.payload.get("as_of") is not None:
            return str(self.payload["as_of"])
        return None

    @classmethod
    def failure(cls, name: str, arguments: dict[str, Any], error: str) -> ToolOutcome:
        return cls(name=name, arguments=arguments, ok=False, error=error)


class Toolbox(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome: ...


def _text_of(content: Any) -> str:
    parts = [getattr(block, "text", "") for block in content or []]
    return "\n".join(part for part in parts if part).strip()


class MCPToolbox:
    """A Toolbox backed by one MCP client session."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    @asynccontextmanager
    async def connect(cls, server: Any, *, timeout: float = 60.0) -> AsyncIterator[MCPToolbox]:
        """`server` is the MCP URL, or an MCPServer instance for in-process tests."""
        async with Client(server, read_timeout_seconds=timeout) as client:
            yield cls(client)

    async def list_tools(self) -> list[ToolSpec]:
        result = await self._client.list_tools()
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.input_schema or {}),
            )
            for tool in result.tools
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        started = time.perf_counter()
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001 - any transport failure becomes a tool error
            return ToolOutcome.failure(name, arguments, f"{type(exc).__name__}: {exc}")
        latency_ms = int((time.perf_counter() - started) * 1000)

        if result.is_error:
            message = _text_of(result.content) or "The tool reported an error."
            return ToolOutcome(
                name=name, arguments=arguments, ok=False, error=message, latency_ms=latency_ms
            )

        payload: Any = result.structured_content
        if payload is None:
            text = _text_of(result.content)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = text
        return ToolOutcome(
            name=name, arguments=arguments, ok=True, payload=payload, latency_ms=latency_ms
        )


def compact_for_model(outcome: ToolOutcome, max_chars: int = 6000) -> str:
    """Serialize a tool outcome for the model, shrinking long lists (e.g. candles) to fit."""
    if not outcome.ok:
        return json.dumps({"error": outcome.error})

    payload = outcome.payload
    text = json.dumps(payload, default=str)
    if len(text) <= max_chars or not isinstance(payload, dict):
        return text if len(text) <= max_chars else text[:max_chars] + "...(truncated)"

    shrunk = json.loads(text)
    holder = shrunk.get("data") if isinstance(shrunk.get("data"), dict) else shrunk
    list_keys = [key for key, value in holder.items() if isinstance(value, list) and value]
    totals = {key: len(holder[key]) for key in list_keys}
    while list_keys and len(json.dumps(shrunk, default=str)) > max_chars:
        longest = max(list_keys, key=lambda key: len(holder[key]))
        if len(holder[longest]) <= 1:
            break
        # Keep the most recent half: candles and statements are ordered oldest first.
        holder[longest] = holder[longest][len(holder[longest]) // 2 :]
    kept = {key: len(holder[key]) for key in list_keys if len(holder[key]) < totals[key]}
    if kept:
        shrunk["truncated"] = {
            key: f"showing the latest {kept[key]} of {totals[key]}" for key in kept
        }
    text = json.dumps(shrunk, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "...(truncated)"
