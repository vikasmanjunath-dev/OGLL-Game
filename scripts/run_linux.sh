#!/bin/bash
# Install (first run) and start LUMEN DRIFT on Linux.
cd "$(dirname "$0")/.." || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install --quiet --upgrade pip && .venv/bin/pip install --quiet -r requirements.txt
fi
exec .venv/bin/python lumen_drift.py "$@"
