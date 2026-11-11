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
| Frontend | http://localhost:5173 | Web app (shows live system status for now) |
| API | http://localhost:8000/health | Health of the API and its dependencies |
| API docs | http://localhost:8000/docs | Interactive OpenAPI docs |
| MCP server | http://localhost:8100/health | Financial Analysis MCP server (`/mcp` endpoint) |
| Postgres | localhost:5432 | Database |
| Redis | localhost:6379 | Celery broker, cache, progress pub/sub |

All ports are bound to `127.0.0.1`, so they are reachable only from your computer.

`GET /health` always answers 200 while the API runs, with `"status": "ok"` when every dependency is
up and `"degraded"` (plus the failing service) when one is down.

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

- Branches: `feature/SCRUM-<key>-short-name`; start every PR title with its Jira key.
- Secrets live only in `.env` (git-ignored); update `.env.example` when you add a setting.
- Every number shown to users must come from a tool result with a source.

## Data and licences

Market data comes from SEC EDGAR, Alpha Vantage and Yahoo Finance (via `yfinance`, development only).
Charts will use TradingView Lightweight Charts; its attribution notice stays visible as its licence
requires.
