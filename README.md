# AI-Powered Stock Market Research and Analysis Platform

[![CI](https://github.com/abduIIahKhaIid/AI-Powered-Stock-Market-Research-and-Analysis-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/abduIIahKhaIid/AI-Powered-Stock-Market-Research-and-Analysis-Platform/actions/workflows/ci.yml)

A conversational assistant for **NASDAQ-listed stocks** that brings market data, company research and
analysis into one chat. It shows candlestick charts and indicators, financial statements and
valuation, comparisons, projections and what-if scenarios, with **sources and assumptions on every
answer**.

> Educational project. Nothing here is financial advice.

## Repository layout

```
backend/        FastAPI API (stock_api), Celery worker and Beat
mcp_server/     Custom Financial Analysis MCP server (financial_mcp)
frontend/       React + Vite + TypeScript web app
sandbox/        Isolated Python sandbox (Sprint 3)
docs/           System design, AWS architecture diagram, Jira backlog
scripts/        Virtual-environment setup scripts
docker-compose.yml
```

## Quick start with Docker (recommended)

Requirements: Docker Desktop.

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
docker compose up --build
```

| Service | URL | What it is |
|---|---|---|
| Frontend | http://localhost:5173 | Chat web app |
| API | http://localhost:8000/health | Health of the API and its dependencies |
| API docs | http://localhost:8000/docs | Interactive OpenAPI docs |
| MCP server | http://localhost:8100/health | Financial Analysis MCP server (`/mcp` endpoint) |
| Postgres | localhost:5432 | Database |
| Redis | localhost:6379 | Celery broker, cache, progress pub/sub |

All ports are bound to `127.0.0.1`, so they are reachable only from your computer.

`GET /health` always answers 200 while the API runs, with `"status": "ok"` when every dependency is
up and `"degraded"` (plus the failing service) when one is down.

## MCP tools

The Financial Analysis MCP server (`http://localhost:8100/mcp`) currently offers:

| Tool | What it returns |
|---|---|
| `search_symbol(query, limit)` | NASDAQ-listed securities matching a ticker or company name |
| `get_quote(symbol)` | Latest daily price, open, high, low, volume, previous close and change |
| `get_price_history(symbol, period, interval)` | OHLCV candles (period `5d`…`max`, interval `5m`…`1mo`) |
| `compute_indicators(symbol, indicators, period, interval)` | SMA, EMA, RSI, MACD, Bollinger Bands, ATR, VWAP: latest and recent values, factual signals, beginner explanations |
| `get_financial_statements(symbol, statement, freq, years)` | Income, balance sheet or cash flow from SEC 10-K/10-Q XBRL data, annual or quarterly, each period linked to its filing |
| `get_valuation_metrics(symbol)` | Price, market cap, P/E, P/S, EV/EBITDA, margins, revenue and EPS growth, each with formula and sourced inputs |
| `get_earnings(symbol)` | Diluted/basic EPS and net income for 5 years and 8 quarters, next earnings date |
| `compare_stocks(symbols, metrics)` | 2 to 5 symbols side by side, one row per metric, a source per cell |
| `run_scenario(symbol, assumptions, cases)` | Base, bull and bear projections (revenue, net income, EPS, DCF-style value per share) with every assumption listed |
| `ping()` | Connectivity check |

SEC data needs `SEC_USER_AGENT` in `.env` set to your name and a contact email (an SEC requirement);
requests stay under 10 per second and responses are cached for a day.

Every tool returns `{data, source, as_of, units}` and rejects symbols that are not NASDAQ-listed.
Prices come from Yahoo Finance via `yfinance` (development source, may be delayed); the symbol list
comes from the Nasdaq Trader directory and is cached for a day.

Check the tools against live data:

```bash
docker compose exec mcp python -m financial_mcp.live_check AAPL
docker compose exec mcp python -m financial_mcp.live_check nvidia
```

## LLM setup

The API talks to the model through one OpenAI-compatible gateway (`backend/stock_api/llm`), so the
model is chosen in `.env` and no code changes are needed to switch.

| Option | `.env` |
|---|---|
| Ollama on Google Colab, exposed with ngrok | `LLM_PROVIDER=ollama`, `LLM_MODEL=qwen3:8b`, `LLM_API_BASE=https://<id>.ngrok-free.app` |
| Ollama on this computer | `LLM_PROVIDER=ollama`, `LLM_API_BASE=http://host.docker.internal:11434` |
| Hosted API | `LLM_PROVIDER=groq` / `gemini` / `openai` / `openrouter` / `anthropic`, `LLM_MODEL`, `LLM_API_KEY` |

For Colab, open `notebooks/ollama_colab_ngrok.ipynb` in a GPU runtime, add your ngrok authtoken as
the Colab secret `NGROK_AUTHTOKEN`, run all cells and copy the printed URL into `LLM_API_BASE`.
The URL changes every time the notebook restarts. The gateway adds `/v1` and the
`ngrok-skip-browser-warning` header for ngrok URLs. Anyone who has the URL can use your model, so
keep it private and stop the notebook when you are done.

Set `LLM_FALLBACK_*` to a hosted provider so chat keeps working when the Colab session ends: the
gateway switches to it only when the primary cannot be reached (connection error, timeout, 5xx,
rate limit or an offline ngrok tunnel), never for bad requests.

Check the configured model, including tool calling:

```bash
docker compose exec api python -m stock_api.llm.check
```

Every call logs provider, model, tokens, estimated cost (`LLM_PRICE_*`), latency and fallback use.
After the primary fails as unreachable, the fallback is used first for `LLM_PRIMARY_COOLDOWN_SECONDS`.

## Asking the assistant

`POST /chat` answers a question as a Server-Sent Events stream. The agent reads the question,
calls the MCP tools it needs (symbol search, quote, price history), and streams the answer.

```json
{"message": "What is NVIDIA's latest price?", "mode": "simple", "conversation_id": null}
```

`mode` is `simple` (beginner-friendly) or `detailed`. Send back the `conversation_id` from the
first event to ask follow-up questions; older turns are summarised automatically.

| Event | Data |
|---|---|
| `conversation` | `conversation_id`, `mode` |
| `status` | `step` the model is working on |
| `token` | a piece of the answer text |
| `tool_call` / `tool_result` | tool name, arguments, ok or error, source, as_of, a small preview |
| `chart` | a price chart spec (symbol, period, interval, candles, source) after `get_price_history` |
| `approval_required` | a sensitive action waits for the user: tool, arguments, reason, estimate (answer with `POST /approvals/{id}`) |
| `approval_result` | `approved`, `denied` or `expired` |
| `sources` | every data source used, with its as_of date |
| `grounding` | `fixing` while figures that did not match the data are corrected, `removed` if any were dropped |
| `done` | full `answer`, `disclaimer`, `assumptions`, `grounding` report, tool trace, tokens, cost and models used |
| `error` | `code` (`llm_unavailable`, `llm_error`, `tools_unavailable`) and `message` |

Every figure in an answer is checked against the data the tools returned (with the rounding its
precision allows, plus simple calculations such as change, percent change, totals, averages and
growth at a rate the user or the answer's assumptions state). A calculation written in the answer
(`173.73 × 1.10 = 191.10`) counts when its arithmetic is right and every input is supported. Figures that do not
match go back to the model to fix, up to two times; any that still fail are removed and the
`grounding.note` says which. Answers about projections or what-if scenarios list their
assumptions and get an extra line in the disclaimer.

Idle streams get a `: keep-alive` comment every 15 seconds, so slow models do not drop the connection.
Each question is limited to `AGENT_MAX_STEPS` model calls and `AGENT_MAX_TOOL_CALLS` tool calls.

Answers about price movement show a candlestick chart with volume (TradingView Lightweight Charts,
attribution kept visible). The chart can switch period (1M to 5Y) through
`GET /prices/{symbol}?period=6mo&interval=1d` and add SMA 20, SMA 50, Bollinger Bands, RSI 14 and
MACD, computed in the browser from the same candles.

**Policy and approvals.** Arguments are checked before any tool runs (ticker format, at most 5
symbols, allowed periods and intervals, at most 10 years). Running model-written code, background
jobs, exports, paid API calls and any tool in `AGENT_APPROVAL_TOOLS` need the user's approval: the
stream sends `approval_required`, the UI shows a card, and `POST /approvals/{id}` with
`{"decision": "approve" | "deny"}` lets the turn continue. Unanswered requests expire after
`APPROVAL_TIMEOUT_SECONDS`. Every tool call and approval is stored in Postgres (`tool_calls`,
`approvals`).

**Background jobs.** Long analyses run in Celery workers (queues `analysis`, `sandbox`,
`ingest`). Each job is a row in the `analysis_jobs` table with status
`queued -> running -> succeeded | failed | cancelled`, progress 0-100 and a stage text.

| Endpoint | What it does |
|---|---|
| `POST /jobs` `{"kind": "indicator_scan", "params": {"symbols": ["AAPL", "NVDA"]}}` | Queue a job (202) |
| `GET /jobs/{id}` | Status, progress, stage, result or error |
| `POST /jobs/{id}/cancel` | Cancel a queued job, or stop a running one at its next step |
| `GET /jobs?conversation_id=&status=` | List jobs |
| `GET /jobs/{id}/result` | Full result of a finished job, also when it was stored in a file |
| `GET /jobs/{id}/files/{name}` | Download a file the job saved, such as `indicator_scan.csv` |
| `GET /analyses` | Saved analyses: finished jobs with a title and a one-line summary |

Job kinds: `indicator_scan` (indicators for up to 10 symbols, 120 s soft / 150 s hard limit) and
`refresh_directory` (run daily by Celery Beat on the `ingest` queue).

**What-if scenarios.** `run_scenario` (MCP) projects one company from its latest fiscal year in
SEC filings. You can set revenue growth, net margin, discount rate, terminal growth and the
horizon; any you leave out come from the last fiscal year or a default. It returns base, bull
and bear cases, or up to 3 cases of your own. For each case you get yearly revenue, net income
and EPS and a DCF-style value per share, and every assumption is listed with the answer. The
chat shows a scenario chart (Recharts) with the case table. Sweeps with more than 3 scenarios
or several symbols (`start_job_scenario_sweep`: a grid or a list of cases, up to 25 scenarios
and 5 symbols) run as a background job, with progress per scenario and a CSV under Saved
analyses.

**Python sandbox.** For calculations no other tool covers (volatility, correlation, simple
backtests), the agent writes Python and calls `run_python_analysis`. That needs your
approval. The worker fetches the price history as CSV files and sends the code to the Sandbox
Runner. The runner runs it in a fresh container: no network, read-only filesystem, non-root,
no capabilities, 512 MB, 1 CPU, 128 processes, 30 s. The result comes back as JSON. See
`sandbox/README.md`.

**Retries and saved results.** Provider, network and rate-limit errors are retried with
exponential backoff (5 s, then 10 s; at most 3 attempts). While a job waits, its stage reads
`Retrying 2 of 3 in 5 s`. Any other error fails the job at once. The job id is the idempotency
key: a finished job never runs again, and each retry starts by removing the files the last
attempt left, so results are never duplicated. Send an `Idempotency-Key` header with
`POST /jobs` and a repeated request returns the first job instead of queuing a second one.
Results up to 64 KB are kept in the job row (JSONB). Larger results and CSV files go to
`JOB_RESULTS_DIR`, a Docker volume (`jobresults`) shared by the API and the worker, so they are
still there after a restart. In production an S3 bucket can take the volume's place.

**Live progress.** Every change to a job is published on the Redis pub/sub channel `job:{id}`.
`GET /jobs/{id}/events` relays it as Server-Sent Events: `job_progress` (status, progress,
stage) for every change, then one `job_done` event with a summary to post in the chat. The
stream re-reads the job row every 5 s, so a missed message never leaves it waiting.

**Jobs from the chat.** Asked to scan three or more symbols, the agent calls
`start_job_indicator_scan` (up to 10 symbols). Like every `start_job*` tool, this needs your
approval first. The answer then shows a progress bar with the current stage and a Cancel
button, and you can keep chatting. When the job finishes, its summary is posted in the chat and
added to the conversation history, so follow-up questions can use it. Set
`AGENT_JOBS_ENABLED=false` to hide the tool.

Try it from the terminal:

```bash
docker compose exec api python -m stock_api.agent.ask "What is NVIDIA's latest price?"
docker compose exec api python -m stock_api.agent.ask --detailed "How did AAPL move over the last month?"
```

## Using the web app

Open http://localhost:5173 and ask a question, or pick one of the starter prompts.

- **Streaming answers.** The answer appears as the model writes it (`POST /api/chat`, read as a
  Server-Sent Events stream). **Stop** cancels a running answer.
- **Tool timeline.** Above each answer, a collapsible list shows every data fetch: the tool, its
  arguments, a short preview of the result, the source, the as-of date and how long it took.
- **Sources and disclaimer.** Each answer ends with the sources it used and the
  not-financial-advice note.
- **Simple / Detailed.** The toggle in the header is sent with every message and remembered.
- **Conversations.** The sidebar lists your chats; they are kept in this browser
  (`localStorage`), and follow-up questions reuse the API's `conversation_id`. On narrow screens
  the sidebar opens from the menu button.
- **Approvals.** Before a sensitive action, such as running Python or starting a background
  job, a card shows:
  - the action and why it needs approval
  - the expected time and cost, for example "12 scenarios, about 12–48 s. No cost."
  - how long it waits for your answer
  - **Approve** and **Deny** buttons
- **Projection banner.** Projection and what-if answers start with a "Projection, not a
  prediction" banner, and their assumptions and the disclaimer are listed below the answer.
- **Accessibility.**
  - Everything works from the keyboard, with visible focus.
  - A "Skip to the message box" link comes first.
  - Every button has a screen-reader label, such as "Approve: Run python analysis" or "Cancel
    Scenario sweep".
  - Charts come with a text summary and their tables.
- **Background jobs.** A scan started from the chat shows a live progress bar under the answer,
  with the stage and, after a temporary error, "Retrying" and the attempt count. Its summary
  arrives as a new message when it finishes, also after a page reload.
- **Saved analyses.** Finished background scans are listed in the sidebar (`GET /api/analyses`).
  Opening one shows its result table, the CSV download and the data source. These are kept on
  the server, so they are still there after a restart or on another browser.

The dev server forwards `/api/*` to the API (`VITE_API_PROXY_TARGET`, default
`http://localhost:8000`).

## Running the Python services without Docker (Windows)

Create the project virtual environment inside this folder (it never touches your system Python):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1
.\.venv\Scripts\Activate.ps1
```

Then, with Postgres and Redis running (for example `docker compose up postgres redis`):

```powershell
# API
cd backend;    uvicorn stock_api.main:app --reload --port 8000
# MCP server (new terminal)
cd mcp_server; python -m financial_mcp.server
# Worker (new terminal)
cd backend;    celery -A stock_api.worker worker -Q analysis,sandbox,ingest --loglevel=info --pool=solo
```

When running outside Docker, point `.env` at localhost (for example
`DATABASE_URL=postgresql://stock:change-me@localhost:5432/stock`, `REDIS_URL=redis://localhost:6379/0`,
`MCP_HEALTH_URL=http://localhost:8100/health`).

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

On Linux or WSL use `scripts/setup_venv.sh` instead.

## Tests and checks

From the repository root, with the virtual environment active:

```bash
pytest                                  # backend and MCP server tests
ruff check . && ruff format --check backend mcp_server
mypy backend mcp_server
cd frontend && npm run lint && npm test && npm run build
```

### Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on pushes to `main`:

| Job | Checks |
|---|---|
| Backend (ruff, mypy, pytest) | lint, format, type check, unit tests |
| Frontend (eslint, vitest, build) | lint, component tests, type check and production build |
| Docker stack smoke test | builds every image, starts postgres, redis, mcp and api, and requires `/health` to report `ok` |

All three must pass before a pull request can be merged into `main`.

## Project documents

- System design: [`docs/system-design.md`](docs/system-design.md)
- AWS architecture diagram: [`docs/architecture/aws-architecture.svg`](docs/architecture/aws-architecture.svg)
- Jira backlog and sprint plan: [`docs/jira-backlog.md`](docs/jira-backlog.md)

## Working agreement

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow. In short:

- Branches: `feature/SCRUM-<key>-short-name`; start every commit message and PR title with its Jira key.
- Secrets live only in `.env` (git-ignored); update `.env.example` when you add a setting.
- Every number shown to users must come from a tool result with a source.

## Data and licences

Market data comes from SEC EDGAR, Alpha Vantage and Yahoo Finance (via `yfinance`, development only).
Charts will use TradingView Lightweight Charts; its attribution notice stays visible as its licence
requires.
