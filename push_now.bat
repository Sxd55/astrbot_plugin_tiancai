@echo off
cd /d "%~dp0"
echo Pushing Batch1 to GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push_now.ps1"
if errorlevel 1 pause
