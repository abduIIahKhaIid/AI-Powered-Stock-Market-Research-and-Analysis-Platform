# Golden-answer eval (SCRUM-39)

An automated accuracy check: 32 questions with known correct answers, asked to the real agent,
and scored. Run it after any change to the model, the prompt or the tools to see whether the
answers got better or worse.

## What is in the set

| Category | Cases | Examples |
|---|---|---|
| technical | 8 | latest close, RSI, SMA 50, MACD, Bollinger Bands, ATR, 3-month high |
| fundamental | 8 | revenue, net income, EPS, P/E, operating margin, free cash flow, cash and debt, profile |
| comparison | 7 | P/E, margins, growth, P/S, EV/EBITDA, prices across 2 or 3 stocks |
| what-if | 7 | value per share and projected revenue or EPS under stated assumptions (one in Roman Urdu) |
| safety | 2 | tool data that contains a prompt injection (SCRUM-40) |

The cases are in [`golden.json`](golden.json). Each lists the question, the figures a correct
answer must contain (with a tolerance), the tools that can answer it, the sources it should cite,
and for safety cases the text and tool calls that must not appear.

## The frozen snapshot

Live prices and filings change every day, so the eval does not use them. The tools run in-process
on a frozen market ([`snapshot.py`](snapshot.py)): seeded daily prices up to 13 November 2026 and
SEC-style filings and company overviews for AAPL, MSFT, NVDA, GOOGL and AMD. The figures are
illustrative and close to the real filings, not copies of them.

Each expected figure also records the tool call and the path it comes from. After a tool or the
snapshot changes, recompute the values with:

```bash
python -m evals fill
```

A test fails until this has been done, so expected values never drift silently.

## Scoring

Every case gets these checks (each 0 to 1); the case score is their mean and a case passes at 80%:

| Check | Passes when |
|---|---|
| figures | each expected figure is in the answer, allowing for units (B, T, %, $) and normal rounding |
| grounding | every figure in the answer matched the tool data first time (a figure fixed after a retry scores 0.5; a removed one 0) |
| disclaimer | a disclaimer is attached, with the projection note only for what-if answers |
| sources | the answer cites the expected source (SEC EDGAR, Alpha Vantage or the price source) |
| tools | one of the expected tools ran |
| mentions | required words are present (e.g. "semiconductor") |
| safety | no forbidden text and no forbidden tool call; a failure fails the case outright |

## Running it

From the repository root, with the virtual environment active:

```bash
python -m evals                                   # offline model, no key needed (must be 100%)
python -m evals --model configured                # the LLM in .env (LLM_PROVIDER, LLM_MODEL, ...)
python -m evals --model configured --category what-if
python -m evals --model configured --cases fund-aapl-pe,cmp-ps --delay 2
```

Or with Docker, without a local Python setup:

```bash
docker compose run --rm evals
docker compose run --rm evals --model configured
```

The **offline model** is a scripted stand-in that makes each case's tool calls and states its
figures. It checks that the harness, the tools, grounding and the disclaimer logic agree with
the golden answers. It does not measure a real model; `--model configured` does.

Every run is saved in `evals/results/` (not committed) and compared with the previous run of the
same model: the score change, cases that started failing and cases that started passing. The
report is printed and also written to `evals/results/latest.md`.

The command exits with code 1 when the score is under `--min-score` (default 80%), a safety case
fails, or the score dropped by more than `--max-drop` (default 5 points) since the previous run.

## In CI

[`.github/workflows/eval.yml`](../.github/workflows/eval.yml) runs on pull requests and pushes that
touch the agent, the LLM gateway, the settings, the MCP tools or the eval, and on demand from the
Actions tab (Run workflow, then pick the model and optionally some case ids).

- The offline model always runs and must score 100%.
- The real model runs when the repository secret `EVAL_LLM_API_KEY` is set. It uses Groq
  `openai/gpt-oss-120b` unless the repository variables `EVAL_LLM_PROVIDER` and `EVAL_LLM_MODEL`
  say otherwise.
- Results are kept in the Actions cache, so each run is compared with the last one, and the report
  appears on the run's summary page. The JSON results are attached as an artifact.

Background-job tools and approval cards are not part of the eval: it measures answers, and an
approval has nobody to click it here.
