"""Stands in for the docker CLI in unit tests: `run` executes the harness directly (no
isolation), `kill` stops it, and `ps`, `rm` and `image inspect` succeed."""

import os
import signal
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_DOCKER_STATE"])
HARNESS = Path(__file__).resolve().parents[1] / "image" / "harness.py"


def main(args: list[str]) -> None:
    command = args[0]
    if command == "run":
        name = args[args.index("--name") + 1]
        (STATE / "commands.txt").open("a").write(" ".join(args) + "\n")
        (STATE / f"{name}.pid").write_text(str(os.getpid()))
        if os.environ.get("FAKE_DOCKER_EXIT"):
            sys.exit(int(os.environ["FAKE_DOCKER_EXIT"]))
        input_dir = STATE / name
        input_dir.mkdir()
        os.environ["SANDBOX_INPUT_DIR"] = str(input_dir)
        os.execv(sys.executable, [sys.executable, str(HARNESS)])
    if command == "kill":
        pid_file = STATE / f"{args[1]}.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        (STATE / "killed.txt").open("a").write(args[1] + "\n")
        return
    if command in ("ps", "rm"):
        return
    if command == "image":
        sys.exit(0 if os.environ.get("FAKE_DOCKER_IMAGE", "1") == "1" else 1)
    sys.exit(f"unknown command {command}")


if __name__ == "__main__":
    main(sys.argv[1:])
