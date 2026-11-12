"""POST /chat: ask a question and receive the answer as a Server-Sent Events stream.

Events, in order: conversation, then status / token / tool_call / tool_result (repeated),
then sources and done. On failure an error event ends the stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import Agent, AgentEvent
from .agent.factory import get_agent
from .llm import LLMConfigError

router = APIRouter(tags=["chat"])

KEEPALIVE_SECONDS = 15.0


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    mode: Literal["simple", "detailed"] = "simple"
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


def format_sse(event: AgentEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"


async def sse_stream(
    events: AsyncIterator[AgentEvent], keepalive_seconds: float = KEEPALIVE_SECONDS
) -> AsyncIterator[str]:
    """Run the agent in its own task and relay its events, with comment pings while idle.

    The pings keep proxies and tunnels from closing the connection while a slow model
    (for example on Colab) is still thinking.
    """
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except Exception as exc:  # noqa: BLE001 - reported to the client as an error event
            await queue.put(
                AgentEvent("error", {"code": "internal", "message": type(exc).__name__})
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            yield format_sse(item)
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def agent_dependency() -> Agent:
    try:
        return get_agent()
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=f"LLM is not configured: {exc}") from exc


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat(
    request: ChatRequest, agent: Annotated[Agent, Depends(agent_dependency)]
) -> StreamingResponse:
    events = agent.run(request.message, mode=request.mode, conversation_id=request.conversation_id)
    return StreamingResponse(
        sse_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
