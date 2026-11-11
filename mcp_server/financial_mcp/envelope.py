"""Standard result shape returned by every MCP tool.

Every tool answers with {data, source, as_of, units} so the agent can always cite where a
number came from and how fresh it is.
"""

from datetime import UTC, date, datetime
from typing import Any

Units = str | dict[str, str] | None


def _iso(value: datetime | date | str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


def envelope(
    data: Any,
    source: str,
    *,
    as_of: datetime | date | str | None = None,
    units: Units = None,
) -> dict[str, Any]:
    """Wrap tool output. `as_of` is when the data is valid (defaults to now)."""
    return {"data": data, "source": source, "as_of": _iso(as_of), "units": units}
