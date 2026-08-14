@echo off
REM Is Midas actually working? - Windows.
REM Usage: double-click check.bat, or run it from a terminal in this folder.
REM
REM start.bat reports that it STARTED, which is not the same as working. The
REM self-hosted stack is four containers deep (db -> postgrest -> rest -> midas)
REM and a failure in the middle looks identical from the outside: the page loads
REM and every table is empty. This checks the whole chain and says which link
REM broke.
REM
REM Windows-only on purpose: this is a deploy-machine tool, and the deploy
REM machine is the office box. There is no check.sh.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VIDEOS="
set "CHANNELS="
set "HEALTH="
set "DASH="

echo Midas Health Check
echo ==================
echo.

echo [1/4] Containers
echo ----------------
docker compose ps
echo.

echo [2/4] Database contents
echo -----------------------
REM Run inside the db container, where POSTGRES_USER and POSTGRES_DB are already
REM set by compose - so this stays correct if either is overridden in .env. The
REM official image trusts local socket connections, hence no password here.
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc 'select count(*) from videos'" > "%TEMP%\midas_videos.txt" 2>nul
if exist "%TEMP%\midas_videos.txt" set /p VIDEOS=<"%TEMP%\midas_videos.txt"
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc 'select count(*) from channels'" > "%TEMP%\midas_channels.txt" 2>nul
if exist "%TEMP%\midas_channels.txt" set /p CHANNELS=<"%TEMP%\midas_channels.txt"

if "!VIDEOS!"=="" (
    echo   videos:   ^<could not query - is the db container up?^>
) else (
    echo   videos:   !VIDEOS!
)
if "!CHANNELS!"=="" (
    echo   channels: ^<could not query^>
) else (
    echo   channels: !CHANNELS!
)
echo.

echo [3/4] App responding
echo --------------------
curl -s -o nul -w "%%{http_code}" --max-time 10 http://localhost:8000/health > "%TEMP%\midas_health.txt" 2>nul
if exist "%TEMP%\midas_health.txt" set /p HEALTH=<"%TEMP%\midas_health.txt"
echo   /health    HTTP !HEALTH!
echo.

echo [4/4] Reads through the full stack
echo ----------------------------------
REM /dashboard is the one unauthenticated endpoint that actually reads rows, so it
REM exercises midas -^> rest ^(nginx^) -^> postgrest -^> db. /health only proves the
REM process is alive.
curl -s -o nul -w "%%{http_code}" --max-time 60 http://localhost:8000/dashboard > "%TEMP%\midas_dash.txt" 2>nul
if exist "%TEMP%\midas_dash.txt" set /p DASH=<"%TEMP%\midas_dash.txt"
echo   /dashboard HTTP !DASH!   ^(first call can take ~30s - it computes, then caches^)
echo.

echo ==================
set "VERDICT=WORKING"
if not "!HEALTH!"=="200"  set "VERDICT=BROKEN"
if not "!DASH!"=="200"    set "VERDICT=BROKEN"
if "!VIDEOS!"=="" set "VERDICT=BROKEN"
if "!VIDEOS!"=="0" set "VERDICT=BROKEN"

if "!VERDICT!"=="WORKING" (
    echo RESULT: WORKING
    echo.
    echo   !VIDEOS! videos across !CHANNELS! channels, and reads work end to end.
    echo   Open the dashboard: http://localhost:8000
) else (
    echo RESULT: SOMETHING IS BROKEN
    echo.
    if "!VIDEOS!"=="" echo   - Could not read the database. Check the db container above.
    if "!VIDEOS!"=="0" echo   - Database is EMPTY. The restore did not happen.
    if not "!HEALTH!"=="200" echo   - The app is not answering on :8000. See: docker compose logs midas
    if "!HEALTH!"=="200" if not "!DASH!"=="200" echo   - App is up but reads fail - that is postgrest or rest ^(nginx^), not the app.
    echo.
    echo   Send the output above plus: docker compose logs --tail 80 midas
)
echo ==================
echo.
pause
