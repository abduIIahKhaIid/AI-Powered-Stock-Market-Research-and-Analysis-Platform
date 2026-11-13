from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import harness


@pytest.fixture(autouse=True)
def input_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(harness, "INPUT_DIR", str(tmp_path))
    return tmp_path


def test_reads_input_files_and_returns_json() -> None:
    envelope = harness.run(
        {
            "code": (
                "import os\n"
                "rows = open(os.path.join(INPUT_DIR, 'prices.csv')).read().split()\n"
                "print('rows', len(rows))\n"
                "result = {'rows': len(rows), 'last': rows[-1]}"
            ),
            "files": {"prices.csv": "close\n1.5\n2.5\n"},
        }
    )
    assert envelope == {
        "ok": True,
        "result": {"rows": 3, "last": "2.5"},
        "stdout": "rows 3\n",
        "error": None,
    }


def test_code_runs_in_the_input_folder() -> None:
    import os

    before = os.getcwd()
    envelope = harness.run(
        {"code": "result = open('prices_AAPL.csv').read()", "files": {"prices_AAPL.csv": "x,1"}}
    )
    assert envelope["result"] == "x,1" and os.getcwd() == before


def test_numpy_and_pandas_values_become_json() -> None:
    frame = pd.DataFrame(
        {"close": [1.0, float("nan")]}, index=pd.to_datetime(["2026-11-12", "2026-11-13"])
    )
    value = harness._plain(
        {
            "n": np.int64(3),
            "x": np.float64(1.5),
            "arr": np.array([1, 2]),
            "frame": frame,
            "series": frame["close"],
            "inf": float("inf"),
            "day": pd.Timestamp("2026-11-13"),
        }
    )
    assert value["n"] == 3 and value["x"] == 1.5 and value["arr"] == [1, 2]
    assert value["frame"]["columns"] == ["close"] and value["frame"]["data"] == [[1.0], [None]]
    assert value["series"] == {"2026-11-12T00:00:00.000": 1.0, "2026-11-13T00:00:00.000": None}
    assert value["inf"] is None and value["day"] == "2026-11-13T00:00:00"


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("x = 1", "NameError: set a variable named result"),
        ("result = b'\\x89PNG'", "bytes and images are not returned"),
        ("result = object()", "object values are not supported"),
        ("x = 1\n\nresult = 1 / 0", "ZeroDivisionError: division by zero (analysis.py line 3)"),
        ("raise SystemExit(3)", "SystemExit: the code called exit(3)"),
        ("result = 'x' * 2_000_000", "result is larger than 1000 KB"),
    ],
)
def test_failures_are_reported(code: str, error: str) -> None:
    envelope = harness.run({"code": code, "files": {}})
    assert envelope["ok"] is False and error in envelope["error"]
