"""Job kinds: what each background job does, its queue and its time limits (SCRUM-32).

Handlers raise TransientJobError for provider, network and rate-limit errors; the runner
then retries the job with exponential backoff (SCRUM-34).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..agent.toolbox import MCPToolbox, ToolOutcome
from .results import ResultStore, check_name
from .store import JobStore

ToolRunner = Callable[[str, dict[str, Any]], ToolOutcome]
# Runs code with input files in the sandbox: (code, files) -> {ok, result, stdout, error, ...}.
SandboxRunner = Callable[[str, dict[str, str]], dict[str, Any]]

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MAX_SCAN_SYMBOLS = 10


class JobCancelled(Exception):
    """The user cancelled the job; it stops at the next progress update."""


class JobInputError(ValueError):
    """The job's parameters are not valid."""


class TransientJobError(RuntimeError):
    """A temporary provider, network or rate-limit error: worth another attempt."""


# Error text from data providers and the MCP transport that means "try again later".
_TRANSIENT = re.compile(
    r"rate.?limit|too many requests|\b429\b|\b50[234]\b|timed? ?out|timeout|temporar"
    r"|unavailable|connection|connect error|network|reset by peer|try again",
    re.IGNORECASE,
)


def is_transient_message(text: str | None) -> bool:
    return bool(text) and bool(_TRANSIENT.search(text or ""))


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransientJobError | ConnectionError | TimeoutError):
        return True
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 502, 503, 504}
    return False


class JobContext:
    """What a handler uses to report progress and save files; also notices cancellation."""

    def __init__(
        self,
        store: JobStore,
        job_id: str,
        attempt: int = 1,
        max_attempts: int = 1,
        results: ResultStore | None = None,
    ) -> None:
        self.store = store
        self.job_id = job_id
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.results = results
        self.files: list[dict[str, Any]] = []

    @property
    def last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts

    def progress(self, percent: int, stage: str) -> None:
        if self.store.get(self.job_id).cancel_requested:
            raise JobCancelled
        self.store.update(self.job_id, progress=percent, stage=stage)

    def check(self, outcome: ToolOutcome) -> ToolOutcome:
        """Raise TransientJobError for a temporary tool error, unless this is the last try."""
        if not outcome.ok and is_transient_message(outcome.error) and not self.last_attempt:
            raise TransientJobError(f"{outcome.name}: {outcome.error}")
        return outcome

    def save_file(self, name: str, data: bytes | str, media_type: str) -> None:
        """Save a downloadable file for this job; saving the same name again replaces it."""
        if self.results is None:
            return
        check_name(name)
        raw = data.encode() if isinstance(data, str) else data
        size = self.results.write(self.job_id, name, raw)
        self.files = [f for f in self.files if f["name"] != name]
        self.files.append({"name": name, "bytes": size, "media_type": media_type})


@dataclass(frozen=True)
class JobKind:
    name: str
    title: str
    queue: str
    soft_limit: int
    hard_limit: int
    validate: Callable[[dict[str, Any]], dict[str, Any]]
    handler: Callable[[dict[str, Any], JobContext], Any]
    max_attempts: int = 3
    # One line for the saved analyses list, from the params and the result.
    summarize: Callable[[dict[str, Any], Any], str] | None = None
    # Markdown posted in the chat when the job finishes, from the params and the result.
    report: Callable[[dict[str, Any], Any], str] | None = None


def mcp_tool_runner(server: Any, timeout: float = 60.0) -> ToolRunner:
    """Calls one MCP tool per invocation, from synchronous worker code."""

    async def call(name: str, arguments: dict[str, Any]) -> ToolOutcome:
        async with MCPToolbox.connect(server, timeout=timeout) as toolbox:
            return await toolbox.call(name, arguments)

    def run(name: str, arguments: dict[str, Any]) -> ToolOutcome:
        return asyncio.run(call(name, arguments))

    return run


# --- indicator scan: indicators for several symbols -------------------------------------


def validate_scan(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("symbols")
    if not isinstance(raw, list) or not raw:
        raise JobInputError("symbols must be a non-empty list of tickers.")
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in raw))
    if len(symbols) > MAX_SCAN_SYMBOLS:
        raise JobInputError(f"Scan at most {MAX_SCAN_SYMBOLS} symbols at a time.")
    bad = [s for s in symbols if not _TICKER.match(s)]
    if bad:
        raise JobInputError(f"Not valid tickers: {', '.join(bad)}.")
    indicators = params.get("indicators") or ["rsi_14", "macd", "sma_50"]
    if not isinstance(indicators, list) or len(indicators) > 8:
        raise JobInputError("indicators must be a list of at most 8 names.")
    period = params.get("period", "6mo")
    if period not in {"1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"}:
        raise JobInputError(f"Unsupported period '{period}'.")
    return {"symbols": symbols, "indicators": indicators, "period": period}


def indicator_scan(runner: ToolRunner) -> Callable[[dict[str, Any], JobContext], Any]:
    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        symbols = params["symbols"]
        rows: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        for index, symbol in enumerate(symbols):
            ctx.progress(
                int(index / len(symbols) * 100),
                f"Computing indicators for {symbol} ({index + 1} of {len(symbols)})",
            )
            outcome = ctx.check(
                runner(
                    "compute_indicators",
                    {
                        "symbol": symbol,
                        "indicators": params["indicators"],
                        "period": params["period"],
                    },
                )
            )
            if not outcome.ok:
                rows[symbol] = {"error": outcome.error}
                continue
            data = outcome.payload["data"]
            rows[symbol] = {
                "last_close": data["last_close"],
                "last_bar": data["last_bar"],
                "latest": {k: v["latest"] for k, v in data["indicators"].items()},
                "signals": data["signals"],
            }
            if outcome.source:
                sources[outcome.source] = outcome.as_of
        ctx.progress(100, "Saving results")
        ctx.save_file("indicator_scan.csv", scan_csv(rows), "text/csv")
        return {
            "symbols": symbols,
            "indicators": params["indicators"],
            "period": params["period"],
            "rows": rows,
            "sources": [{"source": s, "as_of": a} for s, a in sources.items()],
        }

    return handle


def scan_csv(rows: dict[str, Any]) -> str:
    """One line per symbol: last close, the latest value of each indicator, and signals."""
    columns = sorted({name for row in rows.values() for name in row.get("latest", {})})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["symbol", "last_bar", "last_close", *columns, "signals", "error"])
    for symbol, row in rows.items():
        latest = row.get("latest", {})
        values = [
            json.dumps(latest[c]) if isinstance(latest.get(c), dict) else latest.get(c, "")
            for c in columns
        ]
        signals = "; ".join(str(s) for s in row.get("signals", []))
        writer.writerow(
            [
                symbol,
                row.get("last_bar", ""),
                row.get("last_close", ""),
                *values,
                signals,
                row.get("error", ""),
            ]
        )
    return out.getvalue()


def _value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return "n/a" if value is None else str(value)


def report_scan(params: dict[str, Any], result: Any) -> str:
    """Figures copied from the scan result, one line per symbol."""
    lines = [
        f"**Indicator scan finished** for {', '.join(result['symbols'])} "
        f"(period {result['period']})."
    ]
    for symbol, row in result["rows"].items():
        if "error" in row:
            lines.append(f"- **{symbol}**: {row['error']}")
            continue
        values = []
        for indicator, series in row["latest"].items():
            if len(series) == 1:
                values.append(f"{indicator} {_value(next(iter(series.values())))}")
            else:
                parts = ", ".join(f"{name} {_value(v)}" for name, v in series.items())
                values.append(f"{indicator} ({parts})")
        line = (
            f"- **{symbol}**: last close {_value(row['last_close'])} on {row['last_bar'][:10]}; "
            + "; ".join(values)
        )
        if row.get("signals"):
            line += ". Signals: " + "; ".join(s.rstrip(".") for s in row["signals"])
        lines.append(line + ".")
    sources = "; ".join(
        f"{s['source']}, as of {str(s['as_of'])[:10]}" if s.get("as_of") else s["source"]
        for s in result.get("sources", [])
    )
    if sources:
        lines.append(f"\nSource: {sources}.")
    lines.append("The full table and the CSV file are under Saved analyses.")
    return "\n".join(lines)


def summarize_scan(params: dict[str, Any], result: Any) -> str:
    names = ", ".join(params["indicators"])
    return f"{names} for {', '.join(params['symbols'])} ({params['period']})"


# --- scheduled refresh of the NASDAQ symbol directory -----------------------------------


def refresh_directory(runner: ToolRunner) -> Callable[[dict[str, Any], JobContext], Any]:
    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        ctx.progress(10, "Refreshing the NASDAQ symbol directory")
        outcome = ctx.check(runner("search_symbol", {"query": "A", "limit": 1}))
        if not outcome.ok:
            raise RuntimeError(outcome.error or "Directory refresh failed.")
        ctx.progress(100, "Done")
        return {"directory_as_of": outcome.as_of}

    return handle


# --- Python analysis in the sandbox (SCRUM-28) ------------------------------------------

MAX_CODE_CHARS = 20_000
MAX_PYTHON_SYMBOLS = 5
PRICE_COLUMNS = ("time", "open", "high", "low", "close", "volume")


class SandboxCodeError(RuntimeError):
    """The code itself failed in the sandbox; not worth retrying unchanged."""


def validate_python(params: dict[str, Any]) -> dict[str, Any]:
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise JobInputError("code must be the Python source to run.")
    if len(code) > MAX_CODE_CHARS:
        raise JobInputError(f"code must be at most {MAX_CODE_CHARS} characters.")
    raw = params.get("symbols") or []
    if not isinstance(raw, list):
        raise JobInputError("symbols must be a list of tickers.")
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in raw))
    if len(symbols) > MAX_PYTHON_SYMBOLS:
        raise JobInputError(f"Give at most {MAX_PYTHON_SYMBOLS} symbols.")
    bad = [s for s in symbols if not _TICKER.match(s)]
    if bad:
        raise JobInputError(f"Not valid tickers: {', '.join(bad)}.")
    period = params.get("period", "1y")
    if period not in {"1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"}:
        raise JobInputError(f"Unsupported period '{period}'.")
    return {"code": code, "symbols": symbols, "period": period}


def candles_csv(candles: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["date", *PRICE_COLUMNS[1:]])
    for candle in candles:
        writer.writerow([str(candle["time"])[:10], *(candle[c] for c in PRICE_COLUMNS[1:])])
    return out.getvalue()


def python_analysis(
    runner: ToolRunner, sandbox: SandboxRunner
) -> Callable[[dict[str, Any], JobContext], Any]:
    """Fetch the price history as input files, then run the code in the sandbox."""

    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        symbols = params["symbols"]
        files: dict[str, str] = {}
        sources: dict[str, Any] = {}
        for index, symbol in enumerate(symbols):
            ctx.progress(
                int(index / len(symbols) * 50),
                f"Fetching price history for {symbol} ({index + 1} of {len(symbols)})",
            )
            outcome = ctx.check(
                runner(
                    "get_price_history",
                    {"symbol": symbol, "period": params["period"], "interval": "1d"},
                )
            )
            if not outcome.ok:
                raise JobInputError(f"{symbol}: {outcome.error}")
            files[f"prices_{symbol}.csv"] = candles_csv(outcome.payload["data"]["candles"])
            if outcome.source:
                sources[outcome.source] = outcome.as_of
        ctx.progress(60, "Running the code in the sandbox")
        run = sandbox(params["code"], files)
        if not run.get("ok"):
            raise SandboxCodeError(run.get("error") or "The code failed in the sandbox.")
        ctx.progress(100, "Done")
        return {
            "result": run.get("result"),
            "stdout": run.get("stdout") or "",
            "inputs": sorted(files),
            "symbols": symbols,
            "period": params["period"],
            "duration_ms": run.get("duration_ms"),
            "sources": [{"source": s, "as_of": a} for s, a in sources.items()],
        }

    return handle


def report_python(params: dict[str, Any], result: Any) -> str:
    text = json.dumps(result["result"], indent=2)
    if len(text) > 1500:
        text = text[:1500] + "\n…"
    on = f" on {', '.join(result['symbols'])} ({result['period']})" if result["symbols"] else ""
    lines = [f"**Python analysis finished**{on}.", "", "```json", text, "```"]
    sources = "; ".join(
        f"{s['source']}, as of {str(s['as_of'])[:10]}" if s.get("as_of") else s["source"]
        for s in result.get("sources", [])
    )
    if sources:
        lines.append(f"Price data: {sources}.")
    return "\n".join(lines)


# --- scenario sweep (SCRUM-31, SCRUM-75) --------------------------------------------------

MAX_SWEEP_SYMBOLS = 5
MAX_SWEEP_CASES = 25
SWEEP_FIELDS = ("revenue_growth", "net_margin", "discount_rate", "terminal_growth", "horizon_years")


def _case_name(case: dict[str, Any]) -> str:
    short = {
        "revenue_growth": "growth",
        "net_margin": "margin",
        "discount_rate": "discount",
        "terminal_growth": "terminal",
        "horizon_years": "years",
    }
    parts = [
        f"{short[k]} {v:g}{'' if k == 'horizon_years' else '%'}"
        for k, v in case.items()
        if k in SWEEP_FIELDS
    ]
    return ", ".join(parts) or "base"


def validate_sweep(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("symbols")
    if not isinstance(raw, list) or not raw:
        raise JobInputError("symbols must be a non-empty list of tickers.")
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in raw))
    if len(symbols) > MAX_SWEEP_SYMBOLS:
        raise JobInputError(f"Sweep at most {MAX_SWEEP_SYMBOLS} symbols at a time.")
    bad = [s for s in symbols if not _TICKER.match(s)]
    if bad:
        raise JobInputError(f"Not valid tickers: {', '.join(bad)}.")

    cases: list[dict[str, Any]] = []
    grid = params.get("grid")
    if grid:
        if not isinstance(grid, dict) or not set(grid) <= set(SWEEP_FIELDS):
            raise JobInputError(f"grid keys must be among {', '.join(SWEEP_FIELDS)}.")
        combos: list[dict[str, Any]] = [{}]
        for key, values in grid.items():
            if not isinstance(values, list) or not values:
                raise JobInputError(f"grid.{key} must be a non-empty list of numbers.")
            combos = [combo | {key: value} for combo in combos for value in values]
        cases = combos
    elif params.get("cases"):
        if not isinstance(params["cases"], list):
            raise JobInputError("cases must be a list of assumption overrides.")
        cases = [dict(case) for case in params["cases"] if isinstance(case, dict)]
    else:
        raise JobInputError("Give cases (a list of overrides) or grid (values to combine).")
    if len(cases) > MAX_SWEEP_CASES:
        raise JobInputError(f"At most {MAX_SWEEP_CASES} scenarios per sweep; got {len(cases)}.")
    for case in cases:
        unknown = sorted(set(case) - set(SWEEP_FIELDS) - {"name"})
        if unknown:
            raise JobInputError(f"Unknown assumptions: {', '.join(unknown)}.")
        bad_values = [k for k in SWEEP_FIELDS if k in case and not _is_number(case[k])]
        if bad_values:
            raise JobInputError(f"{', '.join(bad_values)} must be numbers (percent).")
        case.setdefault("name", _case_name(case))
    base = params.get("assumptions") or {}
    if not isinstance(base, dict):
        raise JobInputError("assumptions must be an object.")
    return {"symbols": symbols, "cases": cases, "assumptions": base}


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


SWEEP_COLUMNS = (
    "symbol",
    "case",
    "revenue_growth",
    "net_margin",
    "discount_rate",
    "final_year",
    "final_revenue",
    "final_eps",
    "value_per_share",
    "vs_price_pct",
)


def scenario_sweep(runner: ToolRunner) -> Callable[[dict[str, Any], JobContext], Any]:
    """Run each case for each symbol through run_scenario, reporting progress per scenario."""

    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        symbols, cases = params["symbols"], params["cases"]
        total = len(symbols) * len(cases)
        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        starting: dict[str, str] = {}
        sources: dict[str, Any] = {}
        done = 0
        for symbol in symbols:
            for case in cases:
                ctx.progress(
                    int(done / total * 100),
                    f"Scenario {done + 1} of {total}: {symbol}, {case['name']}",
                )
                done += 1
                if symbol in errors:
                    continue
                outcome = ctx.check(
                    runner(
                        "run_scenario",
                        {"symbol": symbol, "assumptions": params["assumptions"], "cases": [case]},
                    )
                )
                if not outcome.ok:
                    errors[symbol] = outcome.error or "The scenario failed."
                    continue
                data = outcome.payload["data"]
                starting.setdefault(symbol, data["assumptions"][0])
                row = data["table"][0]
                rows.append({"symbol": symbol, **{k: row.get(k) for k in SWEEP_COLUMNS[1:]}})
                if outcome.source:
                    sources[outcome.source] = outcome.as_of
        ctx.progress(100, "Saving results")
        ctx.save_file("scenario_sweep.csv", _rows_csv(rows), "text/csv")
        return {
            "symbols": symbols,
            "cases": [case["name"] for case in cases],
            "rows": rows,
            "errors": errors,
            "starting_points": starting,
            "sources": [{"source": s, "as_of": a} for s, a in sources.items()],
        }

    return handle


def _rows_csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(SWEEP_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def report_sweep(params: dict[str, Any], result: Any) -> str:
    rows = result["rows"]
    lines = [
        f"**Scenario sweep finished**: {len(result['cases'])} scenarios for "
        f"{', '.join(result['symbols'])}.",
        "",
        "| Symbol | Scenario | Value per share (USD) | vs price |",
        "|---|---|---:|---:|",
    ]
    for row in rows[:15]:
        vs = row["vs_price_pct"]
        lines.append(
            f"| {row['symbol']} | {row['case']} | {_value(row['value_per_share'])} | "
            f"{'n/a' if vs is None else f'{vs:+.1f}%'} |"
        )
    if len(rows) > 15:
        lines.append(f"\n{len(rows) - 15} more rows are in the CSV under Saved analyses.")
    for symbol, error in result["errors"].items():
        lines.append(f"\n- **{symbol}**: {error}")
    lines.append("\n**Assumptions**")
    lines += [f"- {line}" for line in result["starting_points"].values()]
    lines.append(
        "- Each scenario changes only the listed assumptions; the rest come from the base case."
    )
    sources = "; ".join(
        f"{s['source']}, as of {str(s['as_of'])[:10]}" if s.get("as_of") else s["source"]
        for s in result.get("sources", [])
    )
    if sources:
        lines.append(f"\nSource: {sources}.")
    return "\n".join(lines)


def build_registry(runner: ToolRunner, sandbox: SandboxRunner | None = None) -> dict[str, JobKind]:
    kinds = [
        JobKind(
            "indicator_scan",
            "Indicator scan",
            queue="analysis",
            soft_limit=120,
            hard_limit=150,
            validate=validate_scan,
            handler=indicator_scan(runner),
            summarize=summarize_scan,
            report=report_scan,
        ),
        JobKind(
            "scenario_sweep",
            "Scenario sweep",
            queue="analysis",
            soft_limit=180,
            hard_limit=240,
            validate=validate_sweep,
            handler=scenario_sweep(runner),
            summarize=lambda params, result: (
                f"{len(params['cases'])} scenarios for " + ", ".join(params["symbols"])
            ),
            report=report_sweep,
        ),
        JobKind(
            "refresh_directory",
            "Symbol directory refresh",
            queue="ingest",
            soft_limit=60,
            hard_limit=90,
            validate=lambda params: {},
            handler=refresh_directory(runner),
            summarize=lambda params, result: "NASDAQ symbol directory refreshed",
        ),
    ]
    if sandbox is not None:
        kinds.append(
            JobKind(
                "python_analysis",
                "Python analysis",
                queue="sandbox",
                soft_limit=90,
                hard_limit=120,
                validate=validate_python,
                handler=python_analysis(runner, sandbox),
                summarize=lambda params, result: (
                    "Python analysis"
                    + (f" on {', '.join(params['symbols'])}" if params["symbols"] else "")
                ),
                report=report_python,
            )
        )
    return {kind.name: kind for kind in kinds}
