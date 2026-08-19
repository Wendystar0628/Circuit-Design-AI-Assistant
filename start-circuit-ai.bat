@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { . '.\circuit\Scripts\Activate.ps1'; python main.py }"

if errorlevel 1 (
  echo.
  echo Application exited with an error.
  pause
)
