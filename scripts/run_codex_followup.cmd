@echo off
rem Double-click after run_all_windows: pinned deps (mcp<2) + codex-mcp check + codex-mcp design runs into the newest *_all folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_codex_followup.ps1"
