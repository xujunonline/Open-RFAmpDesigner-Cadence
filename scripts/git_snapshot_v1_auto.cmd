@echo off
rem Same as git_snapshot_v1.cmd but without the Y prompt; safety checks still abort. Local commit + tag only, never pushes.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0git_snapshot_v1.ps1" -Auto
