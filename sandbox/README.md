# Python sandbox

Placeholder for the Sandbox Runner (SCRUM-28, Sprint 3).

Planned contents:
- `image/` – pinned Python image with pandas, numpy and ta, running as a non-root user
- `runner/` – the only service with access to the Docker socket; starts one container per run with
  no network, a read-only filesystem, 512 MB memory, 1 CPU, 128 processes and a 30 s timeout
- `tests/` – escape tests (network, file writes, fork bomb, infinite loop)

See `docs/system-design.md`, section 3.8.
