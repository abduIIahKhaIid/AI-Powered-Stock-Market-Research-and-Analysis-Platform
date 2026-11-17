"""Golden-answer evaluation of the stock research assistant (SCRUM-39).

Run from the repository root with `python -m evals`; see evals/README.md.
"""

import sys
from pathlib import Path

# The eval drives the backend agent and the MCP tools in-process.
_ROOT = Path(__file__).resolve().parents[1]
for _folder in ("backend", "mcp_server"):
    _path = str(_ROOT / _folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)
