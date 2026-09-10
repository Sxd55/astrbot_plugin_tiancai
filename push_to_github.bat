@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push_to_github.ps1"
if errorlevel 1 (
  echo.
  echo Script failed. Log: %~dp0push_log.txt
  pause
)
