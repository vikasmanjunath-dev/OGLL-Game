@echo off
rem Double-click to install (first run) and start LUMEN DRIFT on Windows.
cd /d "%~dp0\.."
if not exist .venv (
  echo First run: creating a private Python environment...
  py -3 -m venv .venv || (echo Python 3 not found - install it from https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
)
.venv\Scripts\python lumen_drift.py %*
