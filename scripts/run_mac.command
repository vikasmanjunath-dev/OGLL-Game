#!/bin/bash
# Double-click this file in Finder (or run it in Terminal) to install and start LUMEN DRIFT on macOS.
cd "$(dirname "$0")/.." || exit 1
if [ ! -d .venv ]; then
  echo "First run: creating a private Python environment..."
  python3 -m venv .venv || { echo "python3 not found - install it from https://www.python.org/downloads/"; read -r -p "Press Enter to close"; exit 1; }
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
.venv/bin/python lumen_drift.py "$@"
