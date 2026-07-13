@echo off
REM Quick start script for Midas (GHCR image) - Windows.
REM Usage: double-click start.bat, or run it from a terminal in this folder.
REM
REM Same job as start.sh: check Docker/.env/client_secret.json + required keys,
REM create the host-mounted job folders (storage shorts_cache logs) so a run
REM that dies on a YouTube quota hit still leaves its artifacts and log on disk,
REM then bring up midas + the bgutil PO-token sidecar via docker compose.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo Midas Quick Start
echo =================

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker is not installed. Install Docker Desktop from https://www.docker.com/products/docker-desktop
    goto :fail
)

if not exist ".env" (
    echo No .env found.
    if exist ".env.example" echo Copy the template and fill it in:  copy .env.example .env
    echo Then run this script again.
    goto :fail
)

if not exist "client_secret.json" (
    echo Missing client_secret.json ^(Google OAuth client^). Place it here, then re-run.
    goto :fail
)

set "MISSING="
for %%K in (SUPABASE_URL SUPABASE_SERVICE_KEY OPENROUTER_API_KEY SESSION_SECRET) do (
    findstr /R /C:"^ *%%K=..*" .env >nul 2>nul
    if errorlevel 1 set "MISSING=!MISSING! %%K"
)
if not "!MISSING!"=="" (
    echo Missing required keys in .env:!MISSING!
    goto :fail
)

echo Config looks good.
echo.

REM Create host-mounted job folders (match the bind mounts in docker-compose.yml).
if not exist "storage\keyframes" mkdir "storage\keyframes"
if not exist "shorts_cache" mkdir "shorts_cache"
if not exist "logs" mkdir "logs"
echo Ready host folders: storage, shorts_cache, logs

echo.
echo Starting Midas (pulls the latest images automatically)...
docker compose up -d
if errorlevel 1 goto :fail

echo Waiting for service to start...
timeout /t 5 /nobreak >nul

curl -s http://localhost:8000/health >nul 2>nul
if errorlevel 1 (
    echo Service started but may still be initializing ^(first run + PO-token warmup can take a minute^).
    echo Check status: docker compose logs -f
) else (
    echo Service is healthy.
    echo.
    echo Midas is running. Open your browser: http://localhost:8000
)

echo.
echo Live logs (host):  type logs\midas.log   ^(or: docker compose logs -f midas^)
echo Job artifacts:     shorts_cache\^<channel^>\tmp
echo To stop:           stop.bat
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
