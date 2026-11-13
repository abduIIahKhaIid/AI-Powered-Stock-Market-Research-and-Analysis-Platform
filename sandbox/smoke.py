"""Smoke test run inside the sandbox runner container: one real run in a fresh container."""

import json
import os
import time
import urllib.request

BASE = "http://localhost:8200"

for _ in range(30):
    try:
        urllib.request.urlopen(f"{BASE}/health/ready", timeout=3)
        break
    except OSError:
        time.sleep(2)

code = "import pandas as pd\nresult = {'total': int(pd.Series([1, 2, 3]).sum())}"
request = urllib.request.Request(
    f"{BASE}/run",
    data=json.dumps({"code": code}).encode(),
    headers={
        "Content-Type": "application/json",
        "X-Sandbox-Token": os.environ.get("SANDBOX_TOKEN", ""),
    },
)
body = json.load(urllib.request.urlopen(request, timeout=90))
print(json.dumps(body, indent=2))
assert body["ok"] and body["result"] == {"total": 6}, body
