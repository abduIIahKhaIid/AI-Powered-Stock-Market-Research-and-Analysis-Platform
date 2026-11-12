"""Check that every figure in an answer comes from the data the tools returned (SCRUM-67).

A figure counts as grounded when it matches, within the rounding its own precision allows:
- a number in this turn's tool results,
- a simple calculation on key tool values (difference, percent change, ratio),
- a number the user wrote, a tool argument, or a figure from earlier in the conversation.

Dates, years, list markers, durations ("50-day", "6 months"), small counts, index names
("S&P 500") and figures in clearly hypothetical sentences ("for example ...") are skipped.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

_DASHES = "-‐‑‒–—−"

NUMBER_RE = re.compile(
    rf"""
    (?<![\w.,/])                                   # not inside a word, ticker or number
    (?P<sign>[{_DASHES}+]\s?)?
    (?P<cur>\$|USD\s?|US\$)?
    (?P<sign2>[{_DASHES}])?
    (?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?P<pct>\s?%)?
    (?:\s?(?P<word>thousand|million|billion|trillion|mn|bn)\b
      |(?P<suf>[kKmMbBtT])(?![\w]))?
    """,
    re.VERBOSE,
)

_MASKS = [
    re.compile(
        rf"\b\d{{4}}[{_DASHES}/]\d{{1,2}}[{_DASHES}/]\d{{1,2}}"
        r"(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?"
    ),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:[AaPp]\.?[Mm]\.?)?"),
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?"
        r"(?:,?\s+\d{4})?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
        r"(?:,?\s+\d{4})?",
        re.IGNORECASE,
    ),
    re.compile(r"(?m)^\s*(?:\d+[.)]|[-*+])\s"),  # list markers
    re.compile(r"\b(?:S&P|S&amp;P)\s?\d+|\bNasdaq[- ]?\d+|\bDow\s?\d+|\bRussell\s?\d+", re.I),
    re.compile(r"\b(?:Q[1-4]|H[12]|FY)\s?'?\d{2,4}\b", re.I),
    re.compile(
        rf"\b\d+(?:\.\d+)?\s?[{_DASHES}]?\s?(?:day|days|week|weeks|month|months|year|years|yr|yrs|"
        r"hour|hours|minute|minutes|min|quarter|quarters|session|sessions|period|periods)\b",
        re.I,
    ),
    re.compile(r"\b(?:SMA|EMA|RSI|MACD|MA|BB)\s?\(?\d+(?:\s?,\s?\d+)*\)?", re.I),
]

_HYPOTHETICAL = re.compile(
    r"\b(?:for example|for instance|e\.g\.|hypothetical|suppose|imagine|let's say|say you|"
    r"misaal|maslan|farz karen|farz karo)\b",
    re.I,
)

_SCALES = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "trillion": 1e12,
}

# Plain integers below this (counts like "2 tools") are not checked.
_SMALL_INTEGER = 10


@dataclass(frozen=True)
class NumberMention:
    text: str
    value: float
    start: int
    end: int
    tolerance: float
    percent: bool = False


@dataclass
class GroundingReport:
    checked: list[NumberMention] = field(default_factory=list)
    ungrounded: list[NumberMention] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.ungrounded

    def unverified_texts(self) -> list[str]:
        seen: list[str] = []
        for mention in self.ungrounded:
            if mention.text not in seen:
                seen.append(mention.text)
        return seen


def _mask(text: str) -> str:
    chars = list(text)
    for pattern in _MASKS:
        for match in pattern.finditer(text):
            for i in range(match.start(), match.end()):
                if not chars[i].isspace():
                    chars[i] = "#"
    return "".join(chars)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in re.finditer(r"(?<=[.!?])\s+|\n+", text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    return spans


def extract_numbers(text: str) -> list[NumberMention]:
    """Figures in `text` that the validator should check."""
    masked = _mask(text)
    hypothetical = [
        (start, end)
        for start, end in _sentence_spans(text)
        if _HYPOTHETICAL.search(text[start:end])
    ]
    mentions: list[NumberMention] = []
    for match in NUMBER_RE.finditer(masked):
        raw_num = match.group("num")
        if raw_num is None or "#" in match.group(0):
            continue
        start, end = match.start(), match.end()
        if any(s <= start < e for s, e in hypothetical):
            continue
        currency = bool(match.group("cur"))
        percent = bool(match.group("pct"))
        word = (match.group("word") or "").lower()
        suffix = (match.group("suf") or "").lower()
        decimals = len(raw_num.split(".")[1]) if "." in raw_num else 0
        base = float(raw_num.replace(",", ""))

        scale = 1.0
        if word:
            scale = _SCALES[word]
        elif suffix and (currency or decimals or base >= _SMALL_INTEGER):
            scale = _SCALES[suffix]
        elif suffix:
            continue  # "3M", "6M": period labels, not amounts

        plain_integer = not (currency or percent or decimals or scale != 1.0)
        if plain_integer and (base < _SMALL_INTEGER or 1900 <= base <= 2100):
            continue

        negative = bool(match.group("sign") or match.group("sign2")) and (
            (match.group("sign") or match.group("sign2") or "").strip() != "+"
        )
        value = base * scale * (-1 if negative else 1)
        tolerance = 0.5 * (10**-decimals) * scale * 1.001 + 1e-9
        mentions.append(
            NumberMention(
                text=text[start:end].strip(),
                value=value,
                start=start,
                end=end,
                tolerance=tolerance,
                percent=percent,
            )
        )
    return mentions


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _series_pairs(series: list[float]) -> list[tuple[float, float]]:
    """The comparisons answers make about a series: overall, range, from the high or low,
    and day to day."""
    if len(series) < 2:
        return []
    first, last, low, high = series[0], series[-1], min(series), max(series)
    pairs = [(last, first), (high, low), (last, high), (last, low)]
    pairs += [(series[i], series[i - 1]) for i in range(1, len(series))]
    return pairs


def _collect(payload: Any, values: list[float], pairs: list[tuple[float, float]]) -> None:
    """Every number in a tool payload, plus the pairs a calculation may combine."""
    if _is_number(payload):
        values.append(float(payload))
    elif isinstance(payload, dict):
        scalars = [float(v) for v in payload.values() if _is_number(v)]
        values.extend(scalars)
        # Compare fields of the same kind only (price vs previous close, high vs low):
        # pairing unrelated fields would make almost any small number look "derived".
        pairs.extend(
            (a, b) for a in scalars for b in scalars if a != b and a * b > 0 and 0.5 <= a / b <= 2
        )
        for value in payload.values():
            if not _is_number(value):
                _collect(value, values, pairs)
    elif isinstance(payload, list | tuple):
        series: dict[str, list[float]] = {}
        plain: list[float] = []
        for item in payload:
            if _is_number(item):
                plain.append(float(item))
            elif isinstance(item, dict):
                for key, value in item.items():
                    if _is_number(value):
                        series.setdefault(key, []).append(float(value))
                    else:
                        _collect(value, values, pairs)
            else:
                _collect(item, values, pairs)
        for numbers in [*series.values(), plain]:
            if not numbers:
                continue
            values.extend(numbers)
            values.append(sum(numbers) / len(numbers))
            pairs.extend(_series_pairs(numbers))


class Evidence:
    """Every value an answer may quote for one turn."""

    def __init__(self) -> None:
        self._values: list[float] = []
        self._pairs: list[tuple[float, float]] = []
        self._sorted: list[float] | None = None

    def add_payload(self, payload: Any) -> None:
        _collect(payload, self._values, self._pairs)
        self._sorted = None

    def add_text(self, text: str) -> None:
        """Numbers the user wrote, tool arguments, earlier answers."""
        for mention in extract_numbers(text):
            self._values.append(mention.value)
        for match in re.finditer(r"\d+(?:\.\d+)?", text.replace(",", "")):
            self._values.append(float(match.group()))
        self._sorted = None

    def _build(self) -> list[float]:
        values = list(self._values)
        for a, b in self._pairs:
            values.append(a - b)
            if b:
                values.append((a - b) / b * 100)
                values.append(a / b)
                values.append(a / b * 100)
        values += [abs(v) for v in values]
        return sorted(set(values))

    @property
    def values(self) -> list[float]:
        if self._sorted is None:
            self._sorted = self._build()
        return self._sorted

    def supports(self, mention: NumberMention) -> bool:
        candidates = [(mention.value, mention.tolerance), (abs(mention.value), mention.tolerance)]
        if mention.percent:
            # A tool may store 5.47% as the fraction 0.0547.
            candidates += [
                (mention.value / 100, mention.tolerance / 100),
                (abs(mention.value) / 100, mention.tolerance / 100),
            ]
        values = self.values
        for target, tolerance in candidates:
            index = bisect.bisect_left(values, target - tolerance)
            if index < len(values) and values[index] <= target + tolerance:
                return True
        return False


_ASSUMPTIONS_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*|__)?\s*(?:Assumptions?|Mafroozat|Mafrozat)\b[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)


def _assumption_spans(text: str) -> list[tuple[int, int]]:
    """The Assumptions heading and its list: stated inputs, not figures from the data."""
    spans = []
    for heading in _ASSUMPTIONS_HEADING.finditer(text):
        end = heading.end()
        for line in re.finditer(r"\n([^\n]*)", text[heading.end() :]):
            content = line.group(1)
            if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", content):
                end = heading.end() + line.end()
            elif content.strip():
                break
            elif end > heading.end():
                break
        spans.append((heading.start(), end))
    return spans


def check_answer(answer: str, evidence: Evidence) -> GroundingReport:
    report = GroundingReport()
    stated = _assumption_spans(answer)
    for mention in extract_numbers(answer):
        if any(start <= mention.start < end for start, end in stated):
            continue
        report.checked.append(mention)
        if not evidence.supports(mention):
            report.ungrounded.append(mention)
    return report


def remove_ungrounded(answer: str, mentions: Iterable[NumberMention]) -> str:
    """Drop each sentence that holds an unverified figure; in table rows blank the cell value."""
    spans = sorted({(m.start, m.end) for m in mentions})
    if not spans:
        return answer
    lines = answer.split("\n")
    out: list[str] = []
    offset = 0
    for line in lines:
        line_start, line_end = offset, offset + len(line)
        offset = line_end + 1
        inside = [(s, e) for s, e in spans if line_start <= s < line_end]
        if not inside:
            out.append(line)
            continue
        if line.lstrip().startswith("|"):
            text = line
            for s, e in sorted(inside, reverse=True):
                text = text[: s - line_start] + "n/a" + text[e - line_start :]
            out.append(text)
            continue
        kept = []
        for s, e in _sentence_spans(line):
            sentence = line[s:e]
            if any(s <= start - line_start < e for start, _ in inside):
                continue
            kept.append(sentence)
        new_line = " ".join(part.strip() for part in kept if part.strip())
        if new_line or not line.strip():
            prefix = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)
            if prefix and new_line and not new_line.startswith(prefix.group().strip()):
                new_line = prefix.group() + new_line
            out.append(new_line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


FIX_PROMPT = (
    "Check of your answer: these figures do not match any value in the tool results: {items}. "
    "Rewrite the complete answer. Quote figures exactly as the tools returned them. If you "
    "calculated a figure, recompute it carefully from the tool values and show the inputs and "
    "the formula. Remove any figure you cannot support. Keep the same language and format, and "
    "reply with the corrected answer only."
)
