@echo off
rem Commit the working tree as the v1 snapshot and tag it v1-decision-points (local only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0git_snapshot_v1.ps1"
