"""Tool calls that a small model wrote as text instead of using the tool-calling API.

Models such as qwen3:4b on Ollama sometimes answer with
``{"name": "run_python_analysis", "arguments": {...}}`` (possibly inside a ```json fence or
<tool_call> tags) as plain content. When that names a tool the model was offered, it is run
as a real tool call instead of being shown to the user as the answer.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..llm import ToolCall

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_TAGS = re.compile(r"</?tool_call>")
MAX_SCAN = 20


def _as_call(value: Any, known: set[str]) -> ToolCall | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("function"), dict):
        value = value["function"]
    name = value.get("name")
    arguments = value.get("arguments", value.get("parameters", {}))
    if not isinstance(name, str) or name not in known:
        return None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, dict):
        return None
    return ToolCall(
        id=f"text_{uuid.uuid4().hex[:12]}",
        name=name,
        arguments=arguments,
        raw_arguments=json.dumps(arguments),
    )


def tool_call_in_text(content: str, known: set[str]) -> ToolCall | None:
    """The first tool call written as a JSON object in the text, if any."""
    text = _TAGS.sub("", _FENCE.sub("", content.strip())).strip()
    if '"name"' not in text:
        return None
    decoder = json.JSONDecoder()
    start = text.find("{")
    tries = 0
    while start != -1 and tries < MAX_SCAN:
        tries += 1
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        call = _as_call(value, known)
        if call is not None:
            return call
        start = text.find("{", start + 1)
    return None
