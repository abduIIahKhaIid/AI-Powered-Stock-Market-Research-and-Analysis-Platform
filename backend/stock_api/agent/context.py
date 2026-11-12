"""System prompt, conversation memory and the summary of older turns (SCRUM-63)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

from ..llm import LLMError, LLMGateway

logger = logging.getLogger("stock_api.agent")

Mode = Literal["simple", "detailed"]

DISCLAIMER = (
    "This is educational information, not financial advice. Data may be delayed or "
    "incomplete; check official sources before making investment decisions."
)

_MODE_RULES: dict[str, str] = {
    "simple": (
        "Explanation mode: SIMPLE. The reader is a beginner. Use short sentences and plain "
        "words, explain any finance term in a few words, and keep the answer under about "
        "150 words unless the question needs more."
    ),
    "detailed": (
        "Explanation mode: DETAILED. The reader is a finance student or analyst. Give a "
        "structured answer with headings or bullet points, the key figures with units and "
        "dates, how each figure is calculated where relevant, and the caveats."
    ),
}


def system_prompt(mode: Mode, today: date | None = None) -> str:
    today = today or date.today()
    return "\n".join(
        [
            "You are a stock research assistant for retail investors, finance students and "
            "beginner analysts.",
            f"Today is {today.isoformat()}.",
            "",
            "Rules:",
            "1. Scope: NASDAQ-listed securities only. If asked about anything else, say it is "
            "outside what this assistant covers.",
            "2. Use the tools for every market figure. Never invent or estimate a price, "
            "volume, ratio or date: quote only numbers that appear in tool results.",
            "3. When the user gives a company name, find the ticker with search_symbol first.",
            "4. After using data, name its source and the as_of date from the tool result.",
            "5. If a tool returns an error, say plainly what could not be retrieved and why.",
            "6. Do not tell the user to buy, sell or hold. Present facts and trade-offs. For "
            "projections or what-if questions, state every assumption.",
            "7. Write the whole answer in the language and script of the user's latest "
            "message. If the user writes Roman Urdu (Urdu in English letters), answer in "
            "Roman Urdu; keep tickers, numbers and finance terms as they are.",
            "8. Copy figures exactly as the tools return them. If you calculate something "
            "(a change or a percentage), show the inputs and the formula.",
            "",
            _MODE_RULES[mode],
        ]
    )


@dataclass
class Conversation:
    summary: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({"summary": self.summary, "messages": self.messages})

    @classmethod
    def from_json(cls, text: str | None) -> Conversation:
        if not text:
            return cls()
        data = json.loads(text)
        return cls(summary=data.get("summary", ""), messages=list(data.get("messages", [])))


class ConversationStore(Protocol):
    async def load(self, conversation_id: str) -> Conversation: ...

    async def save(self, conversation_id: str, conversation: Conversation) -> None: ...


class MemoryConversationStore:
    """Process-local store, for tests and running without Redis."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def load(self, conversation_id: str) -> Conversation:
        return Conversation.from_json(self._data.get(conversation_id))

    async def save(self, conversation_id: str, conversation: Conversation) -> None:
        self._data[conversation_id] = conversation.to_json()


class RedisConversationStore:
    def __init__(self, redis_url: str, ttl_seconds: int = 7 * 24 * 3600) -> None:
        from redis import asyncio as redis_asyncio

        self._redis: Any = redis_asyncio.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"conversation:{conversation_id}"

    async def load(self, conversation_id: str) -> Conversation:
        return Conversation.from_json(await self._redis.get(self._key(conversation_id)))

    async def save(self, conversation_id: str, conversation: Conversation) -> None:
        await self._redis.set(self._key(conversation_id), conversation.to_json(), ex=self._ttl)


def build_messages(
    conversation: Conversation, user_message: str, mode: Mode, today: date | None = None
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(mode, today)}]
    if conversation.summary:
        messages.append(
            {
                "role": "system",
                "content": "Summary of the earlier conversation:\n" + conversation.summary,
            }
        )
    messages.extend(conversation.messages)
    messages.append({"role": "user", "content": user_message})
    return messages


SUMMARY_PROMPT = (
    "Summarize this conversation between a user and a stock research assistant in at most "
    "120 words. Keep the tickers discussed, the figures quoted with their dates and sources, "
    "and what the user wants to know. Do not add anything new."
)


async def remember_turn(
    conversation: Conversation,
    user_message: str,
    answer: str,
    *,
    gateway: LLMGateway | None,
    keep_messages: int = 8,
) -> Conversation:
    """Append the turn; fold messages beyond `keep_messages` into the running summary."""
    conversation.messages.extend(
        [{"role": "user", "content": user_message}, {"role": "assistant", "content": answer}]
    )
    if len(conversation.messages) <= keep_messages:
        return conversation

    older = conversation.messages[:-keep_messages]
    conversation.messages = conversation.messages[-keep_messages:]
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in older)
    if conversation.summary:
        transcript = f"Earlier summary: {conversation.summary}\n{transcript}"
    if gateway is None:
        conversation.summary = transcript[-2000:]
        return conversation
    try:
        result = await gateway.chat(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0,
        )
        conversation.summary = result.content.strip() or conversation.summary
    except LLMError as exc:
        logger.warning("conversation summary failed: %s", exc)
        conversation.summary = transcript[-2000:]
    return conversation
