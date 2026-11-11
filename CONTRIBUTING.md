# Contributing

This guide keeps commits, branches and pull requests consistent and easy to review.
Work is tracked in Jira (project `SCRUM`); every change starts from a Jira issue.

## Workflow

1. Pick an issue from the active sprint and move it to **In Progress** in Jira.
2. Update `main` and create a branch from it:
   ```bash
   git checkout main && git pull
   git checkout -b feature/SCRUM-20-price-tools
   ```
3. Commit in small, focused steps (see the message format below).
4. Run the checks locally (see [Checks](#checks)).
5. Push the branch and open a pull request against `main` using the template.
6. CI must be green before merging. Fix review comments with new commits.
7. Merge, delete the branch, and move the Jira issue to **Done**.

`main` is protected: changes only arrive through pull requests with passing checks.

## Branch names

```
feature/SCRUM-<number>-short-description   new functionality
fix/SCRUM-<number>-short-description       bug fixes
chore/SCRUM-<number>-short-description     tooling, docs, dependencies
```

Use lowercase words separated by hyphens after the key, e.g. `feature/SCRUM-21-sec-edgar-statements`.

## Commit messages

```
SCRUM-<number>: Short summary in the imperative mood

Optional body explaining what changed and why, wrapped at about 72 characters.
- Bullet points are fine for listing several changes
```

- Start with the Jira key so Jira links the commit to the issue.
- Keep the summary under about 72 characters and do not end it with a full stop.
- One logical change per commit; do not mix refactoring with new features.

## Pull requests

- Title: `SCRUM-<number>: Short summary` (same style as commits).
- Fill in every section of the template; link the Jira issue.
- Keep pull requests small enough to review in about 15 minutes. Split large work.
- Add screenshots for UI changes.
- Prefer **Squash and merge** so `main` keeps one commit per issue.

## Checks

Run these from the repository root with the virtual environment active:

```bash
ruff check .
ruff format --check backend mcp_server
mypy backend mcp_server
pytest
```

Frontend:

```bash
cd frontend
npm run lint
npm test
npm run build
```

CI runs the same checks plus a Docker Compose smoke test on every pull request.

## Code style

- **Python 3.12**, formatted and linted with `ruff`, type-checked with `mypy`. Add type hints to
  every function.
- **TypeScript / React**, linted with ESLint. Keep components small and typed.
- Tests live next to the code they cover: `backend/tests`, `mcp_server/tests`, `frontend/src/**/*.test.tsx`.

## Project rules

- **NASDAQ only.** Tools must reject symbols that are not NASDAQ-listed.
- **Grounded numbers.** Any number shown to users must come from a tool result, with its source and
  as-of time. MCP tools return `{data, source, as_of, units}`.
- **Disclaimer.** Projections and what-if answers always show assumptions and a
  "not financial advice" note.
- **Secrets.** Keep keys only in `.env` (git-ignored). Add every new setting to `.env.example`.
- **Data sources.** Respect each provider's limits (SEC EDGAR: descriptive User-Agent, at most
  10 requests per second) and cache responses.

## Definition of done

An issue is done when:

- its acceptance criteria in Jira are met,
- tests cover the new behaviour and all checks pass in CI,
- documentation (README, `docs/`, `.env.example`) is updated where needed,
- the pull request is merged into `main` and the Jira issue is moved to **Done**.
