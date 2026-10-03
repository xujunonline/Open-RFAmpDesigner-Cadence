@echo off
rem Runs the bench commands in scripts\jobs\queue.txt; logs in results\windows_checks\<ts>_job\
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_job_queue.ps1"
