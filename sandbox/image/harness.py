"""Runs one piece of analysis code inside the sandbox container (SCRUM-28).

Reads {"code": ..., "files": {name: text}} as JSON from stdin, writes the files to the input
folder, runs the code and prints one line with the JSON envelope

    __SANDBOX_RESULT__ {"ok": ..., "result": ..., "stdout": ..., "error": ...}

The code returns its answer by setting a variable named ``result`` to JSON data: numbers,
strings, lists and dicts. NumPy and pandas values are converted; images and bytes are not
accepted.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
import traceback
from typing import Any

MARKER = "__SANDBOX_RESULT__ "
INPUT_DIR = os.environ.get("SANDBOX_INPUT_DIR", "/input")
MAX_STDOUT = 20_000
MAX_RESULT_BYTES = 1_000_000


class NotJson(TypeError):
    pass


def _plain(value: Any) -> Any:
    """Turn NumPy and pandas values into JSON data; NaN and infinity become null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, bytes | bytearray | memoryview):
        raise NotJson("result must be JSON data; bytes and images are not returned")
    to_json = getattr(value, "to_json", None)
    if callable(to_json) and hasattr(value, "index"):  # pandas Series or DataFrame
        orient = "split" if hasattr(value, "columns") else "index"
        return _plain(json.loads(to_json(orient=orient, date_format="iso")))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):  # NumPy arrays and scalars
        return _plain(tolist())
    raise NotJson(f"result must be JSON data; {type(value).__name__} values are not supported")


def _error(exc: BaseException) -> str:
    frames = [
        f"line {frame.lineno}"
        for frame in traceback.extract_tb(exc.__traceback__)
        if frame.filename == "analysis.py"
    ]
    where = f" (analysis.py {frames[-1]})" if frames else ""
    return f"{type(exc).__name__}: {exc}{where}"


def run(request: dict[str, Any]) -> dict[str, Any]:
    os.makedirs(INPUT_DIR, exist_ok=True)
    for name, text in (request.get("files") or {}).items():
        with open(os.path.join(INPUT_DIR, os.path.basename(name)), "w", encoding="utf-8") as f:
            f.write(text)

    captured = io.StringIO()
    namespace: dict[str, Any] = {"__name__": "__main__", "INPUT_DIR": INPUT_DIR}
    envelope: dict[str, Any] = {"ok": False, "result": None, "stdout": "", "error": None}
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            exec(compile(request["code"], "analysis.py", "exec"), namespace)  # noqa: S102
        if "result" not in namespace:
            raise NameError("set a variable named result to the data to return")
        result = _plain(namespace["result"])
        if len(json.dumps(result)) > MAX_RESULT_BYTES:
            raise ValueError(f"result is larger than {MAX_RESULT_BYTES // 1000} KB")
        envelope.update(ok=True, result=result)
    except SystemExit as exc:
        envelope["error"] = f"SystemExit: the code called exit({exc.code})"
    except BaseException as exc:  # noqa: BLE001 - every failure is reported in the envelope
        envelope["error"] = _error(exc)
    envelope["stdout"] = captured.getvalue()[-MAX_STDOUT:]
    return envelope


def main() -> None:
    try:
        request = json.loads(sys.stdin.buffer.read())
        envelope = run(request)
    except Exception as exc:  # noqa: BLE001
        envelope = {"ok": False, "result": None, "stdout": "", "error": f"Bad request: {exc}"}
    out = sys.__stdout__ or sys.stdout
    out.write("\n" + MARKER + json.dumps(envelope) + "\n")
    out.flush()


if __name__ == "__main__":
    main()
