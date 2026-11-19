@echo off
REM Double-click to retire this machine as the Midas host. See move-out.ps1.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0move-out.ps1"
