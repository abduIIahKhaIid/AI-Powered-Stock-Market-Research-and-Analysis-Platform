"""The planner loop: model -> tool calls -> results -> model, until an answer (SCRUM-25).

Agent.run() yields AgentEvents that the API streams to the browser as SSE (SCRUM-64).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..llm import ChatResult, LLMError, LLMGateway, LLMUnavailableError, TextDelta
from .context import (
    DISCLAIMER,
    ConversationStore,
    Mode,
    build_messages,
    remember_turn,
)
from .policy import ToolPolicy
from .toolbox import Toolbox, ToolOutcome, compact_for_model

logger = logging.getLogger("stock_api.agent")

ToolboxFactory = Callable[[], AbstractAsyncContextManager[Toolbox]]

NO_ANSWER = "I could not put together an answer this time. Please try rephrasing the question."


@dataclass(frozen=True)
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Totals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    providers: list[str] = field(default_factory=list)
    used_fallback: bool = False

    def add(self, result: ChatResult) -> None:
        self.prompt_tokens += result.usage.prompt_tokens
        self.completion_tokens += result.usage.completion_tokens
        self.cost_usd = round(self.cost_usd + result.usage.cost_usd, 6)
        self.llm_calls += 1
        label = f"{result.provider}/{result.model}"
        if label not in self.providers:
            self.providers.append(label)
        self.used_fallback = self.used_fallback or result.used_fallback

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "models": self.providers,
            "used_fallback": self.used_fallback,
        }


def _root_cause(exc: BaseException) -> BaseException:
    """The first real error inside (possibly nested) exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _preview(outcome: ToolOutcome) -> Any:
    """A small view of the result for the tool timeline in the UI."""
    if not outcome.ok:
        return None
    payload = outcome.payload
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        small = {k: v for k, v in data.items() if not isinstance(v, list | dict)}
        lists = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        if lists:
            small["counts"] = lists
        return small
    if isinstance(data, list):
        return {"count": len(data), "first": data[:3]}
    return str(data)[:300]


class Agent:
    def __init__(
        self,
        gateway: LLMGateway,
        toolbox_factory: ToolboxFactory,
        store: ConversationStore,
        *,
        policy: ToolPolicy | None = None,
        max_steps: int = 6,
        tool_result_max_chars: int = 6000,
        history_messages: int = 8,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.gateway = gateway
        self.toolbox_factory = toolbox_factory
        self.store = store
        self.policy = policy or ToolPolicy()
        self.max_steps = max(1, max_steps)
        self.tool_result_max_chars = tool_result_max_chars
        self.history_messages = history_messages
        self.today = today

    async def run(
        self, message: str, *, mode: Mode = "simple", conversation_id: str | None = None
    ) -> AsyncIterator[AgentEvent]:
        conversation_id = conversation_id or uuid.uuid4().hex
        yield AgentEvent("conversation", {"conversation_id": conversation_id, "mode": mode})

        conversation = await self.store.load(conversation_id)
        messages = build_messages(conversation, message, mode, self.today())
        totals = _Totals()
        sources: dict[tuple[str, str | None], dict[str, Any]] = {}
        tool_trace: list[dict[str, Any]] = []
        answer = ""

        llm_failure: LLMError | None = None
        try:
            async with self.toolbox_factory() as toolbox:
                # LLM errors are caught inside the MCP session: raised through it, they
                # would arrive wrapped in an ExceptionGroup by the session's task group.
                try:
                    specs = self.policy.visible(await toolbox.list_tools())
                    tools = [spec.to_openai() for spec in specs]
                    known = {spec.name for spec in specs}

                    for step in range(1, self.max_steps + 1):
                        # On the last step, or once the tool budget is spent, withhold the
                        # tools so the model has to answer from what it already has.
                        out_of_budget = totals.tool_calls >= self.policy.max_tool_calls
                        final_step = step == self.max_steps or out_of_budget
                        yield AgentEvent("status", {"state": "thinking", "step": step})

                        result: ChatResult | None = None
                        async for event in self.gateway.stream_chat(
                            messages, tools=None if final_step or not tools else tools
                        ):
                            if isinstance(event, TextDelta):
                                yield AgentEvent("token", {"text": event.text, "step": step})
                            else:
                                result = event
                        if result is None:
                            raise LLMError("the model stream ended without a result")
                        totals.add(result)

                        if not result.tool_calls or final_step:
                            answer = result.content.strip()
                            break

                        messages.append(result.assistant_message())
                        for call in result.tool_calls:
                            yield AgentEvent(
                                "tool_call",
                                {
                                    "id": call.id,
                                    "name": call.name,
                                    "arguments": call.arguments,
                                    "step": step,
                                },
                            )
                            refusal = self.policy.refusal(call, totals.tool_calls, known)
                            if refusal:
                                outcome = ToolOutcome.failure(call.name, call.arguments, refusal)
                            else:
                                totals.tool_calls += 1
                                outcome = await toolbox.call(call.name, call.arguments)

                            if outcome.ok and outcome.source:
                                sources[(outcome.source, outcome.as_of)] = {
                                    "source": outcome.source,
                                    "as_of": outcome.as_of,
                                    "tool": call.name,
                                }
                            record = {
                                "id": call.id,
                                "name": call.name,
                                "ok": outcome.ok,
                                "error": outcome.error,
                                "source": outcome.source,
                                "as_of": outcome.as_of,
                                "latency_ms": outcome.latency_ms,
                                "preview": _preview(outcome),
                                "step": step,
                            }
                            tool_trace.append({**record, "arguments": call.arguments})
                            yield AgentEvent("tool_result", record)
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.id,
                                    "content": compact_for_model(
                                        outcome, self.tool_result_max_chars
                                    ),
                                }
                            )
                except LLMError as exc:
                    llm_failure = exc
        except Exception as exc:  # noqa: BLE001 - MCP connection and transport errors
            cause = _root_cause(exc)
            logger.warning("agent: tool server error: %r", cause)
            yield AgentEvent(
                "error",
                {
                    "code": "tools_unavailable",
                    "message": "The market data service could not be reached "
                    f"({type(cause).__name__}: {cause}).",
                },
            )
            return

        if isinstance(llm_failure, LLMUnavailableError):
            logger.warning("agent: no LLM reachable: %s", llm_failure)
            yield AgentEvent(
                "error",
                {
                    "code": "llm_unavailable",
                    "message": "The language model could not be reached. Check that the "
                    "model server is running (Colab/ngrok) or configure a fallback provider.",
                },
            )
            return
        if llm_failure is not None:
            logger.warning("agent: LLM error: %s", llm_failure)
            yield AgentEvent("error", {"code": "llm_error", "message": str(llm_failure)})
            return

        answer = answer or NO_ANSWER
        conversation = await remember_turn(
            conversation,
            message,
            answer,
            gateway=self.gateway,
            keep_messages=self.history_messages,
        )
        await self.store.save(conversation_id, conversation)

        yield AgentEvent("sources", {"sources": list(sources.values())})
        yield AgentEvent(
            "done",
            {
                "conversation_id": conversation_id,
                "answer": answer,
                "disclaimer": DISCLAIMER,
                "tools": tool_trace,
                "usage": totals.as_dict(),
            },
        )
