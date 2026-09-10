@echo off
cd /d "%~dp0"

if not exist "logo.png" (
  if exist "C:\Users\24122\AppData\Local\Claude-3p\local-agent-mode-sessions\a1678ef5\00000000\a865ea4d\uploads\0ee926631c1b369d3bc3a340898b9012.png" (
    copy /Y "C:\Users\24122\AppData\Local\Claude-3p\local-agent-mode-sessions\a1678ef5\00000000\a865ea4d\uploads\0ee926631c1b369d3bc3a340898b9012.png" "logo.png" >nul
    echo copied logo.png
  )
)

echo Pushing v1.7.0 public library manage tab...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push_now.ps1"
if errorlevel 1 pause
