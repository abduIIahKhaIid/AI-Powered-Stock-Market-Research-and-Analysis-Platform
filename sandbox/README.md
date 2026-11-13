# Python sandbox

Model-written Python runs here, one fresh container per run (SCRUM-28).

```
worker ──HTTP (internal "sandbox" network, X-Sandbox-Token)──> sandbox runner ──docker.sock──> container per run
```

- `image/` builds the image each run starts from: Python 3.12 with pinned numpy, pandas, scipy,
  statsmodels and ta. It runs as user 10001. The entry point is `harness.py`.
- `runner/` is the Sandbox Runner (FastAPI, port 8200). It is the only service that mounts the
  Docker socket. It has no published port and sits only on the internal `sandbox` network,
  which the Celery worker also joins.
- `tests/` holds the unit tests (with a fake docker CLI) and the escape tests (real containers).

## One run

1. The worker fetches the data through MCP and sends `POST /run` with
   `{"code": ..., "files": {"prices_AAPL.csv": ...}, "timeout_seconds": 30}`.
2. The runner checks the code statically. It rejects imports of `subprocess`, `socket`,
   `ctypes`, `urllib` and similar modules, `os.system`/`os.fork`/`exec*`,
   `eval`/`exec`/`__import__`, dunder tricks such as `__subclasses__`, and `open()` on literal
   paths outside `/tmp` and `/input`. This check is only defence in depth; the container is the
   boundary.
3. It starts a fresh container with:

   | Limit | Setting |
   |---|---|
   | Network | `--network none` |
   | Filesystem | `--read-only`, tmpfs `/tmp` (64 MB) and `/input` (16 MB), both `noexec,nosuid,nodev` |
   | User | `--user 10001:10001`, `--cap-drop ALL`, `--security-opt no-new-privileges`, default seccomp |
   | Resources | `--memory 512m --memory-swap 512m`, `--cpus 1`, `--pids-limit 128`, `nofile=256` |
   | Time | 30 s wall clock, then `docker kill`; `--rm` removes the container |
   | Output | at most 2 MB on stdout; the result itself at most 1 MB |

4. The code and files go in on stdin. The harness writes the files to `/input`, runs the code
   and prints one JSON line. The code returns data by setting `result`. NumPy and pandas
   values are converted to JSON, NaN becomes `null`, and bytes or images are refused.
5. The runner answers `{ok, result, stdout, error, exit_code, timed_out, duration_ms, blocked}`.

## In the app

The agent tool `run_python_analysis` runs only after the user approves it. It queues a
`python_analysis` job on the `sandbox` Celery queue, so the worker, not the API, calls the
runner. The job writes each symbol's daily prices to `/input/prices_<SYMBOL>.csv`. The tool
waits for the result (up to `AGENT_PYTHON_WAIT_SECONDS`) and returns it to the model.
Grounding then checks every figure in the answer against that result.

## Tests

```bash
pytest sandbox/tests                      # unit tests; the escape tests are skipped

docker build -t stock-sandbox:test sandbox/image
SANDBOX_DOCKER_TESTS=1 SANDBOX_IMAGE=stock-sandbox:test pytest sandbox/tests/test_escape.py
```

The escape tests send code straight to a container, skipping the static check, to show that
each container limit holds on its own:

- the user is 10001, with no capabilities, no-new-privileges and seccomp on
- there is no network, not even DNS, and only the `lo` interface
- nothing can be written outside `/tmp` and `/input`, and `/tmp` fills at 64 MB
- a fork bomb stops at the process limit
- an endless loop is killed at the time limit
- 1 GB of memory is refused or the run is killed
- no container is left behind
- pandas, scipy and ta work on the input files

CI runs these on every pull request (job "Sandbox").

The runner itself runs as root, because it needs the Docker socket, and access to that socket
is root-equivalent on the host. That is why no other service mounts it and why the runner is
not reachable from outside the internal network. Set `SANDBOX_TOKEN` to a long random value.
