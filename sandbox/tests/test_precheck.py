import pytest

from sandbox_runner.precheck import check


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("import subprocess", "importing subprocess"),
        ("import socket\nsocket.socket()", "importing socket"),
        ("from urllib.request import urlopen", "importing from urllib.request"),
        ("import os\nos.system('id')", "os.system"),
        ("from os import fork", "os.fork"),
        ("import ctypes", "importing ctypes"),
        ("eval('1+1')", "eval()"),
        ("__import__('subprocess')", "__import__()"),
        ("().__class__.__bases__[0].__subclasses__()", "__subclasses__"),
        ("open('/etc/passwd').read()", "only be opened under /tmp or /input"),
        ("import sys\nsys.exit(1)", "importing sys"),
        ("def f(:\n  pass", "SyntaxError"),
        ("x = 1\n" * 5000, "longer than"),
    ],
)
def test_blocked_code(code: str, message: str) -> None:
    problems = check(code)
    assert problems and any(message in p for p in problems), problems


def test_normal_analysis_code_passes() -> None:
    code = """
import json, math, os
import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator

class Model:
    def __init__(self, closes):
        self.closes = closes

prices = pd.read_csv(os.path.join(INPUT_DIR, "prices_AAPL.csv"))
rsi = RSIIndicator(prices["close"], window=14).rsi()
with open("/tmp/scratch.txt", "w") as f:
    f.write("ok")
result = {"rsi": float(rsi.iloc[-1]), "mean": float(np.mean(prices["close"]))}
"""
    assert check(code) == []
