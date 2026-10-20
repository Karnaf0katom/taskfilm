@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Run 00-SETUP.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "course.py" --home "%~dp0."
pause
