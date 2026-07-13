@echo off
REM Stop Midas - Windows.
REM Usage: double-click stop.bat, or run it from a terminal in this folder.
REM
REM `docker compose down` stops and removes the containers but leaves the host
REM bind mounts (storage shorts_cache logs) untouched - job artifacts and logs
REM stay on disk so you can recover an upload that failed on a quota hit.

cd /d "%~dp0"

echo Stopping Midas...
docker compose down

echo.
echo Service stopped.
echo.
echo Job artifacts and logs are kept on the host:
echo   shorts_cache   (cut videos awaiting upload)
echo   storage        (keyframes / working data)
echo   logs           (midas.log)
echo.
pause
