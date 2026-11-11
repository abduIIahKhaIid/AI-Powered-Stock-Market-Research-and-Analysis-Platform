# Jira backlog

Board: https://abdullahkhalidai.atlassian.net/jira/software/projects/SCRUM/boards (project key `SCRUM`).

The project has no "Story" issue type, so user stories are **Tasks labelled `story`** (with "As a ... I want ... so that ..." and acceptance criteria), and technical work items are **Subtasks** under them.

Totals: 8 epics, 30 stories (145 story points), 45 subtasks.

| Epic | Stories (points) |
|---|---|
| SCRUM-5 Research & Product Design | SCRUM-13 Market research, personas, competitors (3) ✅ · SCRUM-14 User journeys (3) ✅ · SCRUM-15 Wireframes (5) · SCRUM-16 System design + AWS diagram (5) ✅ |
| SCRUM-6 Project Setup & DevOps | SCRUM-17 Repo skeleton + Docker Compose (5) · SCRUM-18 CI pipeline (3) · SCRUM-19 Contribution guide + PR template (1) |
| SCRUM-7 Market Data & MCP Integrations | SCRUM-20 Custom MCP price tools (8) · SCRUM-21 SEC EDGAR statements (8) · SCRUM-22 Alpha Vantage MCP (3) · SCRUM-23 Caching (5) |
| SCRUM-8 AI Harness & LLM Gateway | SCRUM-24 LLM gateway (5) · SCRUM-25 Planner loop + MCP tool calling (8) · SCRUM-26 Policy engine + approvals (5) · SCRUM-27 Grounding, sources, disclaimer (5) |
| SCRUM-9 Analysis Engine & Python Sandbox | SCRUM-28 Sandbox Runner (8) · SCRUM-29 Technical indicators (5) · SCRUM-30 Valuation + comparison (5) · SCRUM-31 Projections + what-if (8) |
| SCRUM-10 Background Processing | SCRUM-32 Celery + job lifecycle (5) · SCRUM-33 Live job progress (5) · SCRUM-34 Retries, idempotency, saved results (5) |
| SCRUM-11 Frontend Chat & Visualisation | SCRUM-35 Chat + streaming + tool timeline (5) · SCRUM-36 Candlestick + indicator charts (5) · SCRUM-37 Fundamentals charts + tables (3) · SCRUM-38 Approval, progress, disclaimer UI (3) |
| SCRUM-12 Quality, Security & Delivery | SCRUM-39 Golden-answer eval set (5) · SCRUM-40 Security hardening (3) · SCRUM-41 Deploy to AWS EC2, optional (5) · SCRUM-42 Presentation + demo (3) |

✅ = Done.

## Working rules
- Branch name: `feature/SCRUM-<key>-short-name`; PR title starts with the Jira key so Jira links the PR.
- Suggested first sprint: SCRUM-17, SCRUM-18, SCRUM-20, SCRUM-24, SCRUM-25, SCRUM-35 (the thinnest end-to-end slice: ask a question → MCP price tool → streamed answer).
