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
evals/          Golden-answer eval: accuracy and grounding checks (SCRUM-39)
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

| URL | What it is |
|---|---|
| http://localhost:8080 | Chat web app (sign in or create an account first) |
| http://localhost:8080/api/health | Health of the API and its dependencies |
| http://localhost:8080/api/docs | Interactive OpenAPI docs |

Nginx is the only service with a published port, bound to `127.0.0.1` so it is reachable only
from your computer. It serves the web app at `/` and the API at `/api`. Postgres, Redis, the MCP
server, the API and the Sandbox Runner are internal. To reach them directly while debugging, add
`-f docker-compose.debug.yml` (it publishes Postgres 5432, Redis 6379, MCP 8100, API 8000 and Vite
5173 on 127.0.0.1):

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up
```

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
| `get_company_overview(symbol)` | Sector, industry, description, market cap, P/E, dividend yield, beta, 52-week range (Alpha Vantage) |
| `run_scenario(symbol, assumptions, cases)` | Base, bull and bear projections (revenue, net income, EPS, DCF-style value per share) with every assumption listed |
| `ping()` | Connectivity check |

SEC data needs `SEC_USER_AGENT` in `.env` set to your name and a contact email (an SEC requirement);
requests stay under 10 per second and responses are cached for a day.

Every tool returns `{data, source, as_of, units}` and rejects symbols that are not NASDAQ-listed.
Prices come from Yahoo Finance via `yfinance` (development source, may be delayed); the symbol list
comes from the Nasdaq Trader directory and is cached for a day.

**Caching and durable data.**
- **Redis cache.** The MCP server caches tool results in Redis: quotes for 60 s, intraday
  candles for 5 minutes, daily and longer candles for 12 hours. The logs show `cache hit` or
  `cache miss` for every call. If Redis is down, the tools still work, uncached.
- **Postgres.**
  - Every daily candle fetched goes into `ohlcv_daily`.
  - Every SEC statement line item read goes into `financial_facts`, with its form, filing
    date and link.
  - When both Yahoo Finance and Alpha Vantage fail, `get_price_history` serves the saved daily
    candles and says so in its source line.
- **Daily refresh.** Celery Beat runs the `refresh_watchlist` job every day at 21:37 UTC,
  after the US close. For each symbol in `WATCHED_SYMBOLS` it fetches a year of daily prices
  and the annual and quarterly statements, saves them and clears that symbol's cached results.
  It uses the maintenance tool `refresh_market_data`, which the model never sees.
- **Migrations.** Tables are managed with Alembic (`backend/migrations`). The api container
  runs `alembic upgrade head` on start. By hand: `docker compose exec api alembic upgrade head`.

**Second source: Alpha Vantage.** With `ALPHAVANTAGE_API_KEY` set in `.env`, the MCP server
connects to the official remote Alpha Vantage MCP server (`https://mcp.alphavantage.co/mcp`).
- **Fallback.** When Yahoo Finance fails, `get_quote`, `get_price_history` and
  `compute_indicators` use Alpha Vantage's daily, weekly or monthly bars automatically.
  Indicators are computed from those bars the same way. The source line says which provider
  was used ("Alpha Vantage (official MCP server), used because … failed").
- **Company profile.** `get_company_overview` returns sector, industry, description, market
  cap, P/E, dividend yield, beta, 52-week range and analyst target from Alpha Vantage.
- **Free-tier limits.** The free tier allows about 25 requests a day, so:
  - responses are cached on disk (quotes 60 s, daily bars 12 h, weekly and monthly bars and
    overviews 24 h)
  - calls are at least 1.2 s apart
  - the server stops at `ALPHAVANTAGE_DAILY_LIMIT` and then serves stale cached copies when
    it has them
  - the free daily series covers the last 100 trading days only
- **Logs.** Cache hits and misses are logged.

The client calls a function directly when the server lists it, or through its `TOOL_CALL`
entry point otherwise.

Check the tools against live data:

```bash
docker compose exec mcp python -m financial_mcp.live_check AAPL
docker compose exec mcp python -m financial_mcp.live_check nvidia
docker compose exec mcp python -m financial_mcp.live_check AAPL --alpha-vantage   # 2 Alpha Vantage requests
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

Open http://localhost:8080, create an account (or sign in), and ask a question or pick one of
the starter cards. Your name and **Sign out** are at the bottom of the sidebar; conversations are
kept per user.

The interface is built with Tailwind CSS and Radix UI components (shadcn/ui style, in
`frontend/src/components/ui`), with Motion for animations. It has light and dark themes.

- **Streaming answers.** The answer appears as the model writes it (`POST /api/chat`, read as a
  Server-Sent Events stream). **Stop** cancels a running answer.
- **Thinking panel.** Above each answer, a collapsible panel shows the assistant's work:
  - the model's reasoning, when the model streams it (`<think>` blocks or a `reasoning_content`
    field, sent as `thinking` events)
  - every data fetch, with its arguments, a short preview of the result, the source, the as-of
    date and how long it took; each step opens to its full input and output
  - It opens by itself while the assistant works, then folds into one line
    ("Thought for 6s · used 2 tools") when the answer starts. Click it to open it again.
- **Sources and disclaimer.** Each answer ends with the sources it used and the
  not-financial-advice note.
- **Message actions.** Under each answer: copy, helpful / not helpful (kept with the
  conversation) and ask again.
- **Edit a question.** Hover a question and choose the pencil to change it. The edited question
  is answered again and every answer after it is replaced. The API forgets the replaced turns
  too (`rewind_turns` in `POST /api/chat`), so the new answer does not build on them. **Ask
  again** works the same way for the last question.
- **Rename a chat.** Use the pencil next to a chat in the sidebar (or double-click it), type the
  new title and press Enter.
- **Simple / Detailed.** The toggle in the message box is sent with every message and
  remembered.
- **Conversations.** The sidebar lists your chats grouped by date (Today, Yesterday, Previous 7
  days…), with a search box. Chats are kept in this browser (`localStorage`), and follow-up
  questions reuse the API's `conversation_id`. On narrow screens the sidebar opens from the menu
  button; on wide screens it can be hidden.
- **Settings.** The gear in the header opens the settings, saved in this browser:
  - theme: light, dark or system
  - chain of thought: full (reasoning and tools), tools only, or hidden (a status line only)
  - animations on or off. They are also off when the operating system asks for less motion.
- **Animated charts.** Price charts draw their candles in from left to right with a fixed price
  scale, and the last price counts up. Fundamentals bars grow, scenario lines draw one case after
  another, and comparison tables show a small bar per value.
- **Fundamentals and comparisons.**
  - `get_financial_statements` (income) and `get_earnings` answers come with a Recharts chart.
    You can switch it between revenue and net income bars, diluted EPS bars, and gross,
    operating and net margin lines. A data table is under it.
  - `compare_stocks` answers come with a table you can sort by clicking a column heading.
    Missing values go last, and hovering one explains why it is missing.
  - Scenario charts show the bear-to-bull range as a shaded band (the "fan") around the base
    case.
  - Every chart and table has **Sources** and **Assumptions** chips. They open the filing links
    and the formulas, settings and assumptions behind it.
  - **Export CSV** first asks for approval with the same card as other sensitive actions. Then
    the file is built in your browser.
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

In Docker, Nginx forwards `/api/*` to the API. Without Docker, the Vite dev server does the same
(`VITE_API_PROXY_TARGET`, default `http://localhost:8000`).

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

After pulling changes to `frontend/package.json` or `frontend/vite.config.ts`, rebuild the web
app image: `docker compose up -d --build frontend` (the container mounts only `frontend/src`).

On Linux or WSL use `scripts/setup_venv.sh` instead.

## Tests and checks

From the repository root, with the virtual environment active:

```bash
pytest                                  # backend, MCP server, sandbox and eval tests
ruff check . && ruff format --check backend mcp_server sandbox evals
mypy backend mcp_server sandbox evals
cd frontend && npm run lint && npm test && npm run build
```

### Accuracy eval

`python -m evals` asks 32 golden questions (technical, fundamental, comparison, what-if and
prompt-injection cases) on a frozen market snapshot and scores numeric accuracy, grounding, the
disclaimer and sources. Add `--model configured` to evaluate the LLM in `.env`. Each run is saved
and compared with the previous one. See [`evals/README.md`](evals/README.md).

### Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on pushes to `main`:

| Job | Checks |
|---|---|
| Backend (ruff, mypy, pytest) | lint, format, type check, unit tests |
| Frontend (eslint, vitest, build) | lint, component tests, type check and production build |
| Docker stack smoke test | builds every image, starts postgres, redis, mcp and api, and requires `/health` to report `ok` |

All of them must pass before a pull request can be merged into `main`.

`.github/workflows/eval.yml` runs the accuracy eval when the agent, the prompt, the LLM settings, the
MCP tools or the eval change, and on demand. The offline model must score 100%; the real model runs
when the `EVAL_LLM_API_KEY` secret is set.

## Security

The stack is hardened as follows (SCRUM-40); details and the AWS plan are in
[`docs/security.md`](docs/security.md).

- **One way in.** Only Nginx publishes a port. It adds security headers and limits sign-in
  attempts per address.
- **Sign-in.** Every API endpoint except `/health` and `/auth/*` needs a JWT. Accounts use scrypt
  password hashes. Each user sees only their own jobs, saved analyses, approvals and
  conversations. Set `JWT_SECRET` in `.env`; `AUTH_SIGNUP_CODE` makes sign-up invite-only.
- **Rate limits per user.** 20 chat messages a minute and 20 job requests a minute by default,
  answered with HTTP 429 and `Retry-After`.
- **Secrets.** Secrets live only in `.env` locally (git-ignored) and in SSM Parameter Store on
  AWS. CI runs `scripts/check_secrets.py` on every change.
- **Dependency scan.** CI runs `pip-audit` on all Python requirements and `npm audit` on the web
  app.
- **Prompt injection.**
  - Text from tools reaches the model only as quoted data, with chat-template tokens defused.
  - The system prompt tells the model never to follow instructions found in tool data.
  - Anything the model asks for afterwards still goes through the policy and approval cards.
  - Tests cover this (`backend/tests/test_prompt_injection.py`), and two eval cases check a real
    model.

## Project documents

- System design: [`docs/system-design.md`](docs/system-design.md)
- Security: [`docs/security.md`](docs/security.md)
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
