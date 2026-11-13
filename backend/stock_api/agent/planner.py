"""The planner loop: model -> tool calls -> results -> model, until an answer (SCRUM-25).

Agent.run() yields AgentEvents that the API streams to the browser as SSE (SCRUM-64).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from ..chart_spec import chart_from_tool
from ..llm import ChatResult, LLMError, LLMGateway, LLMUnavailableError, TextDelta
from .approvals import ApprovalBroker, ApprovalRequest
from .audit import AuditLog
from .composer import (
    disclaimer_for,
    extract_assumptions,
    is_projection,
    source_link,
    tool_assumptions,
)
from .context import (
    ConversationStore,
    Mode,
    build_messages,
    remember_turn,
)
from .grounding import FIX_PROMPT, Evidence, GroundingReport, check_answer, remove_ungrounded
from .policy import JOB_PREFIXES, ToolPolicy
from .text_tools import tool_call_in_text
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


def _estimate(toolbox: Any, name: str, arguments: dict[str, Any]) -> str | None:
    """Time and cost of this call, when the toolbox can tell (shown on the approval card)."""
    estimate = getattr(toolbox, "estimate", None)
    return estimate(name, arguments) if callable(estimate) else None


def _job_started(name: str, outcome: ToolOutcome, conversation_id: str) -> dict[str, Any] | None:
    """The job_started event for a tool call that queued a background job."""
    payload = outcome.payload
    if not (outcome.ok and name.startswith(JOB_PREFIXES) and isinstance(payload, dict)):
        return None
    if not isinstance(payload.get("job_id"), str):
        return None
    return {
        "job_id": payload["job_id"],
        "kind": payload.get("kind"),
        "title": payload.get("title"),
        "conversation_id": conversation_id,
    }


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
        max_fix_attempts: int = 2,
        approvals: ApprovalBroker | None = None,
        audit: AuditLog | None = None,
        today: Callable[[], date] = date.today,
        toolbox_wrapper: Callable[[Toolbox, str], Toolbox] | None = None,
    ) -> None:
        self.gateway = gateway
        self.toolbox_factory = toolbox_factory
        self.store = store
        self.policy = policy or ToolPolicy()
        self.max_steps = max(1, max_steps)
        self.tool_result_max_chars = tool_result_max_chars
        self.history_messages = history_messages
        self.max_fix_attempts = max_fix_attempts
        self.approvals = approvals
        self.audit = audit
        self.today = today
        # Adds harness tools (such as starting background jobs) for one conversation.
        self.toolbox_wrapper = toolbox_wrapper

    async def _audit_call(
        self,
        conversation_id: str,
        call_id: str,
        outcome: ToolOutcome,
        approval_id: str | None,
    ) -> None:
        if self.audit is None:
            return
        await self.audit.tool_call(
            {
                "conversation_id": conversation_id,
                "call_id": call_id,
                "tool": outcome.name,
                "arguments": outcome.arguments,
                "ok": outcome.ok,
                "error": outcome.error,
                "source": outcome.source,
                "as_of": outcome.as_of,
                "latency_ms": outcome.latency_ms,
                "approval_id": approval_id,
            }
        )

    async def _audit_approval(self, request: ApprovalRequest) -> None:
        if self.audit is not None:
            await self.audit.approval(request)

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
        outcomes: list[ToolOutcome] = []
        answer = ""
        last_step = 0

        # Figures the answer may quote: the question, earlier turns and (below) tool data.
        evidence = Evidence()
        evidence.add_text(message)
        evidence.add_text(conversation.summary)
        for earlier in conversation.messages:
            if earlier.get("role") == "assistant":
                evidence.add_text(earlier.get("content", ""))

        llm_failure: LLMError | None = None
        try:
            async with self.toolbox_factory() as mcp_toolbox:
                toolbox: Toolbox = mcp_toolbox
                if self.toolbox_wrapper is not None:
                    toolbox = self.toolbox_wrapper(mcp_toolbox, conversation_id)
                # LLM errors are caught inside the MCP session: raised through it, they
                # would arrive wrapped in an ExceptionGroup by the session's task group.
                try:
                    specs = self.policy.visible(await toolbox.list_tools())
                    tools = [spec.to_openai() for spec in specs]
                    known = {spec.name for spec in specs}
                    by_name = {spec.name: spec for spec in specs}

                    for step in range(1, self.max_steps + 1):
                        # On the last step, or once the tool budget is spent, withhold the
                        # tools so the model has to answer from what it already has.
                        out_of_budget = totals.tool_calls >= self.policy.max_tool_calls
                        final_step = step == self.max_steps or out_of_budget
                        last_step = step
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

                        if not result.tool_calls and not final_step and tools:
                            # A small model may write the tool call as text; run it anyway.
                            written = tool_call_in_text(result.content, known)
                            if written is not None:
                                logger.info("agent: tool call %s was written as text", written.name)
                                result = replace(result, content="", tool_calls=[written])

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
                            approval_id: str | None = None
                            needed = (
                                None if refusal else self.policy.approval_for(by_name[call.name])
                            )
                            if needed and self.approvals is None:
                                refusal = (
                                    "This action needs your approval, which is not available here."
                                )
                            elif needed and self.approvals is not None:
                                request = self.approvals.open(
                                    conversation_id,
                                    call.name,
                                    call.arguments,
                                    needed["reason"],
                                    _estimate(toolbox, call.name, call.arguments)
                                    or needed.get("estimate"),
                                )
                                approval_id = request.id
                                await self._audit_approval(request)
                                yield AgentEvent(
                                    "approval_required",
                                    {
                                        "approval_id": request.id,
                                        "tool": call.name,
                                        "arguments": call.arguments,
                                        "reason": request.reason,
                                        "estimate": request.estimate,
                                        "expires_in": self.approvals.timeout_seconds,
                                        "step": step,
                                    },
                                )
                                status = await self.approvals.wait(request.id)
                                await self._audit_approval(request)
                                yield AgentEvent(
                                    "approval_result",
                                    {"approval_id": request.id, "status": status},
                                )
                                if status == "denied":
                                    refusal = "The user declined this action, so it was not run."
                                elif status != "approved":
                                    refusal = (
                                        "The approval request got no answer in time, so the "
                                        "action was not run."
                                    )
                            if refusal:
                                outcome = ToolOutcome.failure(call.name, call.arguments, refusal)
                            else:
                                totals.tool_calls += 1
                                outcome = await toolbox.call(call.name, call.arguments)
                            await self._audit_call(conversation_id, call.id, outcome, approval_id)

                            evidence.add_text(json.dumps(call.arguments))
                            if outcome.ok:
                                evidence.add_payload(outcome.payload)
                                outcomes.append(outcome)
                            if outcome.ok and outcome.source:
                                sources[(outcome.source, outcome.as_of)] = {
                                    "source": outcome.source,
                                    "as_of": outcome.as_of,
                                    "tool": call.name,
                                    "link": source_link(outcome.payload),
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
                            chart = (
                                chart_from_tool(call.name, outcome.payload) if outcome.ok else None
                            )
                            if chart is not None:
                                yield AgentEvent("chart", chart)
                            started = _job_started(call.name, outcome, conversation_id)
                            if started is not None:
                                yield AgentEvent("job_started", started)
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

        # Grounding (SCRUM-27): every figure must come from the data. Unmatched figures go
        # back to the model up to max_fix_attempts times; whatever still fails is removed.
        report: GroundingReport = check_answer(answer, evidence)
        attempts = 0
        flagged: list[str] = []
        while not report.ok and attempts < self.max_fix_attempts:
            attempts += 1
            unverified = report.unverified_texts()
            flagged += [item for item in unverified if item not in flagged]
            yield AgentEvent(
                "grounding",
                {"state": "fixing", "attempt": attempts, "unverified": unverified},
            )
            step = last_step + attempts
            yield AgentEvent("status", {"state": "fixing", "step": step})
            fix_messages = [
                *messages,
                {"role": "assistant", "content": answer},
                {"role": "user", "content": FIX_PROMPT.format(items=", ".join(unverified))},
            ]
            revised: ChatResult | None = None
            try:
                async for event in self.gateway.stream_chat(fix_messages):
                    if isinstance(event, TextDelta):
                        yield AgentEvent("token", {"text": event.text, "step": step})
                    else:
                        revised = event
            except LLMError as exc:
                logger.warning("agent: grounding fix failed: %s", exc)
                break
            if revised is not None:
                totals.add(revised)
                if revised.content.strip():
                    answer = revised.content.strip()
            report = check_answer(answer, evidence)

        removed: list[str] = []
        if not report.ok:
            removed = report.unverified_texts()
            answer = remove_ungrounded(answer, report.ungrounded)
            report = check_answer(answer, evidence)
        grounding: dict[str, Any] = {
            "status": (
                "removed"
                if removed
                else "corrected"
                if attempts
                else "verified"
                if report.checked
                else "no_figures"
            ),
            "checked": len(report.checked),
            "attempts": attempts,
            "flagged": flagged,
            "removed": removed,
            "note": (
                f"{len(removed)} figure{'s' if len(removed) != 1 else ''} could not be matched "
                f"to the source data and {'were' if len(removed) != 1 else 'was'} removed: "
                + ", ".join(removed)
                + "."
                if removed
                else None
            ),
        }
        if removed:
            yield AgentEvent("grounding", {"state": "removed", "removed": removed})
        answer = answer or NO_ANSWER

        assumptions = list(dict.fromkeys(extract_assumptions(answer) + tool_assumptions(outcomes)))
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
                "disclaimer": disclaimer_for(message, answer, assumptions),
                "projection": is_projection(message, answer, assumptions),
                "assumptions": assumptions,
                "grounding": grounding,
                "tools": tool_trace,
                "usage": totals.as_dict(),
            },
        )
