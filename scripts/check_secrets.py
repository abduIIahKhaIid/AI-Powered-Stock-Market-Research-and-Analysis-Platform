"""Fail when a secret is committed (SCRUM-40). Run in CI and before pushing:

    python scripts/check_secrets.py

Checks every file git tracks for:
- .env files other than .env.example (real settings live only in an untracked .env)
- well-known key formats (Groq, OpenAI, Anthropic, AWS, Google, GitHub, Slack, ngrok, private keys)
- secret settings in .env.example that are not left empty
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "Groq API key": re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    "ngrok auth token": re.compile(r"\b[0-9][A-Za-z0-9]{26}_[A-Za-z0-9]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
}
# Settings whose value must stay empty in .env.example.
SECRET_SETTING = re.compile(
    r"^(?P<name>[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|AUTHTOKEN))=(?P<value>.*)$"
)
EXAMPLE_PLACEHOLDERS = {"", '""', "''", "change-me"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".woff", ".woff2"}
SKIP_FILES = {"package-lock.json"}


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [ROOT / name for name in out.split("\0") if name]


def problems_in(path: Path, text: str) -> list[str]:
    found: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{relative}:{line}: looks like a {label}")
    if path.name == ".env.example":
        for number, line in enumerate(text.splitlines(), start=1):
            setting = SECRET_SETTING.match(line.strip())
            if setting and setting["value"].strip() not in EXAMPLE_PLACEHOLDERS:
                found.append(
                    f"{relative}:{number}: {setting['name']} must be empty in .env.example"
                )
    return found


def main() -> int:
    problems: list[str] = []
    for path in tracked_files():
        name = path.name
        if name.startswith(".env") and name != ".env.example":
            problems.append(
                f"{path.relative_to(ROOT).as_posix()}: .env files must not be committed"
            )
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or name in SKIP_FILES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        problems += problems_in(path, text)
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} possible secret(s) found. Move them to .env (not committed).")
        return 1
    print("No secrets found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
