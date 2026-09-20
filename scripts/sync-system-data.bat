@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_system_data.ps1"
if errorlevel 1 pause
