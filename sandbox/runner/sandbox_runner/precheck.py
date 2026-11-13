"""A static check before any code runs (defence in depth; the container is the real boundary).

It rejects code that reaches for processes, the network, low-level memory or dynamic code,
and code that opens files outside /tmp and /input by a literal path.
"""

from __future__ import annotations

import ast

BLOCKED_MODULES = frozenset(
    {
        "subprocess",
        "socket",
        "ssl",
        "ctypes",
        "cffi",
        "multiprocessing",
        "concurrent",
        "asyncio",
        "selectors",
        "signal",
        "pty",
        "fcntl",
        "resource",
        "mmap",
        "importlib",
        "urllib",
        "http",
        "ftplib",
        "smtplib",
        "telnetlib",
        "requests",
        "httpx",
        "aiohttp",
        "webbrowser",
        "pickle",
        "marshal",
        "shelve",
        "code",
        "codeop",
        "pdb",
        "sys",
        "builtins",
    }
)
BLOCKED_OS = frozenset(
    {
        "system",
        "popen",
        "fork",
        "forkpty",
        "kill",
        "killpg",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "posix_spawn",
        "posix_spawnp",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "setuid",
        "setgid",
        "chroot",
        "putenv",
        "unsetenv",
    }
)
BLOCKED_CALLS = frozenset(
    {"eval", "exec", "compile", "__import__", "globals", "locals", "vars", "breakpoint", "input"}
)
BLOCKED_DUNDERS = frozenset(
    {
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__closure__",
        "__bases__",
        "__base__",
        "__mro__",
        "__class__",
        "__dict__",
        "__getattribute__",
        "__import__",
        "__loader__",
        "__spec__",
        "__reduce__",
        "__reduce_ex__",
        "__self__",
        "__func__",
        "__frame__",
        "f_globals",
        "f_back",
        "gi_frame",
        "tb_frame",
    }
)
ALLOWED_PREFIXES = ("/tmp/", "/input/")
MAX_CODE_CHARS = 20_000


def check(code: str) -> list[str]:
    """Reasons the code may not run; empty when it passes."""
    if len(code) > MAX_CODE_CHARS:
        return [f"The code is longer than {MAX_CODE_CHARS} characters."]
    try:
        tree = ast.parse(code, filename="analysis.py")
    except SyntaxError as exc:
        return [f"SyntaxError: {exc.msg} (line {exc.lineno})"]

    problems: list[str] = []

    def flag(node: ast.AST, message: str) -> None:
        problems.append(f"line {getattr(node, 'lineno', '?')}: {message}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_MODULES:
                    flag(node, f"importing {alias.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in BLOCKED_MODULES:
                flag(node, f"importing from {node.module} is not allowed")
            if module == "os":
                for alias in node.names:
                    if alias.name in BLOCKED_OS:
                        flag(node, f"os.{alias.name} is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_DUNDERS:
                flag(node, f"access to {node.attr} is not allowed")
            elif (
                isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in BLOCKED_OS
            ):
                flag(node, f"os.{node.attr} is not allowed")
        elif isinstance(node, ast.Name) and node.id in BLOCKED_CALLS | BLOCKED_DUNDERS:
            flag(node, f"{node.id}() is not allowed")
        elif isinstance(node, ast.Call) and _is_open(node.func) and node.args:
            path = node.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                if path.value.startswith("/") and not path.value.startswith(ALLOWED_PREFIXES):
                    flag(node, f"files may only be opened under /tmp or /input, not {path.value}")
    return problems


def _is_open(func: ast.expr) -> bool:
    return (isinstance(func, ast.Name) and func.id == "open") or (
        isinstance(func, ast.Attribute) and func.attr == "open"
    )
