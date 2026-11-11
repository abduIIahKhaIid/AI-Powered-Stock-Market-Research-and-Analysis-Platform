#!/usr/bin/env bash
# Creates a Linux virtual environment for this project.
#   Default location: .venv-linux inside the project folder (for Linux / WSL machines).
#   Override with VENV_DIR=/some/path to keep the venv on a faster local disk
#   (useful when the project folder is on a slow mounted drive).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV_DIR="${VENV_DIR:-$PWD/.venv-linux}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.tmp/uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$PWD/.tmp/uv-python}"
# default uv download host may be blocked; GitHub mirror works
export UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-https://github.com/astral-sh/python-build-standalone/releases/download}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  uv venv "$VENV_DIR" --python 3.12 --link-mode copy
fi
if [ -f requirements.txt ]; then
  VIRTUAL_ENV="$VENV_DIR" uv pip install --link-mode copy -r requirements.txt
fi
echo "Done. Activate with: source $VENV_DIR/bin/activate"
