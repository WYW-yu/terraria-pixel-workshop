@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not installed or not found in PATH.
  echo Please install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" during installation, then run this again.
  pause
  exit /b 1
)
python run.py
