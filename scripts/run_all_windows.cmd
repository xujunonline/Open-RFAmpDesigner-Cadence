@echo off
rem Double-click: checks + LLM backbone runs + Cadence run. Logs: results\windows_checks\<ts>_all\
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_all_windows.ps1"
echo.
echo Finished. You can close this window.
pause
