# System Design: AI-Powered Stock Market Research and Analysis Platform

**Status:** Draft v1 · **Scope:** NASDAQ-listed securities · **Deployment target:** AWS EC2 (Docker Compose), local Docker first

---

## 1. Goals and non-goals

### Goals
- One conversational interface that combines market data, company research and analysis.
- Technical analysis (candlesticks, indicators, trends, volume) and fundamental analysis (statements, earnings, valuation, performance).
- Python-powered calculations: comparisons, projections, what-if scenarios.
- Every answer is **grounded**: numbers come from tools, with sources, timestamps and assumptions shown.
- Long analyses run in the background with progress, retries and saved results.

### Non-goals (v1)
- Trade execution, brokerage integration, portfolio custody.
- Personalised investment advice or buy/sell recommendations.
- Markets other than NASDAQ; real-time tick data (end-of-day and delayed data is enough).

### Users
| Persona | Need | Explanation mode |
|---|---|---|
| Retail investor | "Is this company healthy? How has it moved?" | Simple by default |
| Finance student | Learn ratios, indicators, how a DCF works on real data | Detailed, with formulas |
| Beginner analyst | Compare peers quickly, export tables, test assumptions | Detailed, with tables |

---

## 2. Architecture overview

```
Browser (React SPA)
   │  HTTPS (REST + SSE)
   ▼
Nginx (TLS, static files, reverse proxy)
   ▼
FastAPI API ──► Agent Harness ──► LLM Gateway (OpenAI-compatible client) ──► LLM provider(s)
   │                 │
   │                 ├─► Policy Engine (tool allowlist, approvals, limits)
   │                 ├─► MCP Client ──► Financial Analysis MCP (custom)
   │                 │                └─► Alpha Vantage MCP (existing)
   │                 └─► Grounding Validator (numbers ↔ tool results)
   │
   ├─► Redis (Celery broker, cache, progress pub/sub)
   │      ▼
   │   Celery workers ──► Sandbox Runner ──► ephemeral Python containers (no network)
   │
   └─► PostgreSQL (users, chats, tool-call audit, jobs, market data cache)
          S3 (reports, exports, large job results)
```

All application services run as containers on one EC2 host (Docker Compose). The same Compose file runs locally. The design keeps clear service boundaries so each piece can later move to a managed service (see §11).

---

## 3. Components

### 3.1 Frontend (React + Vite + TypeScript)
- Chat panel with streaming answers (SSE), tool-activity timeline, approval prompts.
- **Simple / Detailed** toggle sent with each message.
- Charts rendered from JSON chart specs returned by the backend:
  - **TradingView Lightweight Charts**: candlesticks, volume, moving averages, Bollinger Bands, RSI/MACD panes. The TradingView attribution logo stays visible (license requirement).
  - **Recharts**: revenue/EPS bars, margin lines, peer comparison bars, scenario fans.
- Tables (sortable) for statements and comparisons; every table/chart shows "Sources" and "Assumptions" chips.
- Persistent disclaimer on projections and what-if answers.

### 3.2 API (FastAPI)
- REST: auth, conversations, messages, jobs, symbols, exports.
- SSE stream per conversation: `token`, `tool_call`, `tool_result`, `approval_required`, `job_progress`, `chart`, `table`, `sources`, `done`.
- JWT auth, per-user rate limits (Redis token bucket), request IDs for tracing.

### 3.3 Agent Harness
Coordinates the model, context, permissions and analysis workflow.

1. **Context builder**: system prompt (role, NASDAQ scope, grounding rules, disclaimer policy, explanation mode), recent turns, conversation summary, pinned symbols.
2. **Planner loop**: model → tool calls → results → model, with a max-step budget (e.g. 8 tool calls per turn) and token budget.
3. **Policy engine** (permissions):
   - Tool allowlist per role.
   - Argument validation (symbol must be NASDAQ-listed, date ranges capped, max symbols per comparison).
   - **Approval required** for sensitive actions: running model-written Python, starting background jobs above a cost/time threshold, exports, any paid-API call.
4. **Router**: quick work runs inline; long work (multi-year backtests, DCF sweeps, multi-symbol scenarios) becomes a Celery job.
5. **Grounding validator**: every number in the final answer must match a value in this turn's tool results (with tolerance for rounding/unit formatting). Unmatched numbers → the model is asked to fix or remove them before the answer is sent.
6. **Response composer**: attaches sources (provider, endpoint, filing link, as-of timestamp), assumptions, and the disclaimer where needed.

### 3.4 LLM Gateway
- A thin OpenAI-compatible client (`backend/stock_api/llm`) with presets for Ollama, Groq, Gemini, OpenAI,
  OpenRouter and Anthropic, so the provider is a config change in `.env`.
- Optional fallback provider, used only when the primary cannot be reached.
- Options: local Ollama (development), hosted APIs (demo). Colab + ngrok only for experiments (free Colab sessions can be terminated and remote proxies are disallowed).
- Retries with backoff, timeouts, token/cost logging per request. `python -m stock_api.llm.check` verifies tool calling.

### 3.5 MCP layer (hybrid)
**Custom Financial Analysis MCP server** (Python, MCP SDK, runs as its own container):

| Tool | Purpose |
|---|---|
| `search_symbol(query)` | Resolve company name → NASDAQ ticker (from the Nasdaq symbol directory) |
| `get_quote(symbol)` | Latest price, change, volume, as-of time |
| `get_price_history(symbol, period, interval)` | OHLCV candles |
| `compute_indicators(symbol, indicators, period)` | SMA/EMA, RSI, MACD, Bollinger, ATR, VWAP |
| `get_financial_statements(symbol, statement, freq, years)` | Income, balance sheet, cash flow (SEC EDGAR XBRL) |
| `get_valuation_metrics(symbol)` | P/E, P/S, EV/EBITDA, margins, growth |
| `get_earnings(symbol)` | EPS history, surprises, upcoming date |
| `compare_stocks(symbols, metrics)` | Side-by-side table |
| `run_scenario(symbol, assumptions)` | What-if / projection (inline or queued) |
| `run_python(code, inputs)` | Sandboxed custom analysis (approval required) |

Every tool returns `{data, source, as_of, units, assumptions?}` so grounding and source display are automatic.

**Existing MCP server:** Alpha Vantage's official MCP server (quotes, time series, technical indicators, company overview) as a second data source and fallback.

### 3.6 Data sources
| Data | Primary | Notes |
|---|---|---|
| Symbol universe | Nasdaq Trader symbol directory (`nasdaqlisted.txt`) | Refreshed daily; enforces NASDAQ-only scope |
| Prices / OHLCV | yfinance (development), Alpha Vantage MCP | yfinance is unofficial: cache aggressively, handle breakage |
| Fundamentals | SEC EDGAR XBRL API (`companyfacts`, `submissions`) | Free, official, linkable to filings; needs a descriptive User-Agent and ≤10 req/s |
| Company overview | Alpha Vantage | Free tier has tight limits → cache |

Caching: Redis for hot data (quotes 60 s, intraday 5 min, daily candles 12 h); Postgres for durable data (daily OHLCV, statements per filing).

### 3.7 Background processing (Celery + Redis)
- Queues: `analysis` (default), `sandbox` (code runs), `ingest` (scheduled data refresh via Celery Beat).
- Job lifecycle in `analysis_jobs`: `queued → running → succeeded | failed | cancelled`, with `progress` 0-100 and `stage` text.
- Progress: worker publishes to Redis pub/sub `job:{id}` → API relays as SSE `job_progress`.
- Retries: `autoretry_for` network/provider errors, exponential backoff, max 3 attempts; tasks are **idempotent** (job id = idempotency key; results upserted).
- Time limits: soft 120 s / hard 180 s per task (tunable per job type).
- Results: small results in Postgres JSONB; large ones (CSV/Parquet/report) in S3 with a reference in Postgres.

### 3.8 Python sandbox
- A **Sandbox Runner** service is the only component with access to the Docker socket. Workers call it over an internal API: `run(code, input_files) → {stdout, result_json, files}`.
- Each run starts a fresh container from a pinned image (Python + pandas, numpy, scipy, ta, statsmodels):
  - `--network none`, `--read-only`, tmpfs `/tmp` (64 MB), non-root user
  - `--memory 512m`, `--cpus 1`, `--pids-limit 128`, wall-clock timeout 30 s
  - default seccomp profile, `no-new-privileges`, all capabilities dropped
- Data goes in as input files prepared by the worker (fetched through MCP tools), never fetched by the code itself.
- Output must be JSON (tables, series, chart specs); images are not returned.
- Static pre-check before running: block `os.system`, `subprocess`, sockets, `open` outside `/tmp`/`/input`.

### 3.9 Storage (PostgreSQL)
Core tables: `users`, `conversations`, `messages`, `tool_calls` (audit: tool, args, result hash, latency, approved_by), `approvals`, `analysis_jobs`, `job_results`, `symbols`, `ohlcv_daily`, `financial_facts`, `sources`.

---

## 4. Key flows

### 4.1 Chat question (inline)
1. User asks "Compare AAPL and MSFT margins over 5 years" (Detailed mode).
2. API stores the message, opens SSE, calls the harness.
3. Harness builds context → LLM decides tools → policy checks → MCP calls `get_financial_statements` ×2 → `compare_stocks`.
4. Results (with sources) return to the LLM → draft answer + chart spec + table.
5. Grounding validator checks numbers → composer adds sources/assumptions → streamed to the UI.

### 4.2 Long analysis (background)
1. User asks for a 3-scenario DCF sweep.
2. Policy engine marks it as a long/approval-required job → UI shows an approval card.
3. On approval: API creates `analysis_jobs` row, enqueues Celery task, returns `job_id`.
4. Worker fetches data via MCP → sends code + inputs to Sandbox Runner → container runs → JSON result.
5. Worker saves the result (Postgres/S3), publishes progress along the way.
6. On completion the harness summarises the result in the chat with sources and assumptions.

### 4.3 Failure handling
- Provider error → retry with backoff → fallback provider (Alpha Vantage ↔ yfinance) → clear message if all fail.
- Sandbox timeout/OOM → job `failed` with reason; user can retry with smaller scope.
- LLM produces ungrounded numbers twice → answer sent without those numbers plus a note.

---

## 5. Security
- Secrets in AWS SSM Parameter Store (loaded at container start); `.env` only locally.
- Security groups: only 443 (and 80 → redirect) open publicly; SSH only via SSM Session Manager.
- Internal services (Redis, Postgres, MCP, Sandbox Runner) on a private Docker network, no published ports.
- Input validation on all tool arguments; prompt-injection guard: tool outputs are treated as data, never as instructions.
- Audit log of every tool call and approval.

## 6. Observability
- Structured JSON logs → CloudWatch Logs (Docker `awslogs` driver).
- Metrics: request latency, tool latency, LLM tokens/cost, job duration, failure rate.
- Celery Flower (internal only) for queue inspection.

## 7. CI/CD (GitHub Actions)
- On PR: `ruff` + `mypy` + `pytest` (backend), `eslint` + `vitest` + build (frontend), Docker build check.
- On merge to `main`: build images → push to Amazon ECR → deploy to EC2 via SSM Run Command (`docker compose pull && up -d`).

## 8. Deployment (AWS)
- Region e.g. `us-east-1`; one VPC, public subnet with the EC2 host (Elastic IP), Route 53 DNS, TLS via Let's Encrypt on Nginx.
- EC2 instance sized for the full stack (≥ 8 GB RAM recommended, e.g. `m7i-flex.large`); EBS gp3 volume for Postgres/Redis data with daily snapshots.
- S3 bucket for reports/exports and Postgres backups.

## 9. Compliance and UX safety
- Disclaimer on every projection/what-if: educational information, not financial advice.
- Assumptions listed explicitly (growth rate, discount rate, horizon, data as-of date).
- Data attribution shown (SEC EDGAR, Alpha Vantage, Yahoo Finance via yfinance, TradingView chart attribution).

## 10. Testing strategy
- Unit tests: indicator math against known values, XBRL parsing, policy rules.
- Contract tests: each MCP tool returns the standard envelope.
- Golden-answer eval set: ~30 questions with expected numbers/sources; run on every model/provider change.
- Sandbox escape tests: network access, file writes, fork bombs must all fail.

## 11. Scale-out path (later)
| Today (single EC2) | Later (managed) |
|---|---|
| API / workers / MCP containers | ECS Fargate services |
| Postgres container | Amazon RDS for PostgreSQL |
| Redis container | Amazon ElastiCache |
| Nginx on EC2 | Application Load Balancer + CloudFront |
| Sandbox Runner on EC2 | Dedicated EC2 sandbox host or Firecracker-based service |
