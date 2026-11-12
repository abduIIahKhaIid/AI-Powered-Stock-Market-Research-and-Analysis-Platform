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
