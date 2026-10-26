@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Client Codex
if errorlevel 1 echo Installation did not complete. Read the message above.
pause
