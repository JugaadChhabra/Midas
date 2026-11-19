# move-out.ps1 -- retire THIS Windows machine as the Midas host.
#
# Run: double-click move-out.bat in the midas folder
#   (or: powershell -NoProfile -ExecutionPolicy Bypass -File .\move-out.ps1)
#
# What it does, in order. It stops at the first thing that goes wrong, before
# anything irreversible:
#   1. checks the files the new machine needs are all here
#   2. waits for Shorts cuts in progress to finish (at most 20 minutes)
#   3. stops the app, so nothing writes to the database or YouTube any more
#   4. records row counts, then publishes a final NAS snapshot of the stopped
#      database (the new machine restores itself from that snapshot)
#   5. stops every container
#   6. packs the config into a zip on the Desktop, for the Mac mini
#   7. renames .env, so this machine cannot start Midas again by accident
#      (two hosts would both write to YouTube, and this one's midnight backup
#      would overwrite the NAS snapshot with stale data)
#
# Everything it prints is also written to logs\move-out.txt.
# ASCII only on purpose: Windows PowerShell 5.1 misreads a BOM-less UTF-8 file.

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8
New-Item -ItemType Directory -Force -Path logs | Out-Null
$Log = Join-Path $PSScriptRoot 'logs\move-out.txt'
Set-Content -Encoding utf8 -Path $Log -Value "move-out started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

function Say([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Encoding utf8 -Path $Log -Value $line
}

function Fail([string]$msg) {
    Say ''
    Say "STOPPED: $msg"
    Say "Send logs\move-out.txt to Claude."
    Read-Host 'Press Enter to close'
    exit 1
}

# Run a native command, echo and log its output, return its exit code.
function Native([scriptblock]$Cmd) {
    & $Cmd 2>&1 | ForEach-Object {
        $text = "$PSItem"
        Write-Host $text
        Add-Content -Encoding utf8 -Path $Log -Value $text
    }
    return $LASTEXITCODE
}

# One psql query against the live DB; returns its rows as strings.
function Sql([string]$query) {
    $rows = & docker compose exec -T db psql -U midas midas -tA -F '|' -c $query 2>&1 | ForEach-Object { "$PSItem" }
    if ($LASTEXITCODE -ne 0) { Fail "psql failed: $rows" }
    return $rows | Where-Object { $PSItem.Trim() -ne '' }
}

Say 'Midas move-out (this machine stops being the host)'
Say '==================================================='

# ---- 1. Preflight: nothing has been touched yet --------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'docker is not on PATH. Is Docker Desktop running?' }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker is not running. Start Docker Desktop, wait for it, then run this again.' }

$required = @('.env', 'docker-compose.yml', 'client_secret.json', 'deploy\postgrest-proxy.conf')
foreach ($f in $required) {
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { Fail "Missing $f in $PSScriptRoot (run this from the midas folder)." }
}
if (-not (Test-Path -LiteralPath 'move-in.sh' -PathType Leaf)) {
    Say 'Note: move-in.sh is not in this folder, so it will not be in the zip. Copy it to the Mac separately.'
}

$code = Native { docker compose config -q }
if ($code -ne 0) { Fail 'docker compose config failed (see above).' }

# The database must be up to count rows and take the snapshot.
$code = Native { docker compose up -d db }
if ($code -ne 0) { Fail 'Could not start the db container.' }
$healthy = $false
for ($i = 0; $i -lt 24; $i++) {
    $state = (& docker inspect -f '{{.State.Health.Status}}' midas-db 2>$null)
    if ("$state".Trim() -eq 'healthy') { $healthy = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $healthy) { Fail 'The db container did not become healthy within 2 minutes.' }
Say 'Database is up.'

# ---- 2. Let Shorts cuts in progress finish -------------------------------
$appRunning = ((& docker compose ps --status running --services 2>$null) -contains 'midas')
if ($appRunning) {
    $deadline = (Get-Date).AddMinutes(20)
    while ($true) {
        $busy = [int]((Sql "select count(1) from shorts_jobs where status in ('DOWNLOADING','ANALYSING','RENDERING','UPLOADING');") | Select-Object -First 1)
        if ($busy -eq 0) { Say 'No Shorts job is mid-cut.'; break }
        if ((Get-Date) -gt $deadline) {
            Say "$busy Shorts job(s) still running after 20 minutes. Stopping anyway: they will show as failed ('server restarted mid-job') and can be re-run on the Mac."
            break
        }
        Say "$busy Shorts job(s) still cutting; checking again in 60 s (gives up waiting at $($deadline.ToString('HH:mm')))."
        Start-Sleep -Seconds 60
    }
} else {
    Say 'The app was not running.'
}

# ---- 3. Stop the app: from here on nothing writes -------------------------
$code = Native { docker compose stop midas }
if ($code -ne 0) { Fail 'Could not stop the midas container.' }
Say 'App stopped. Nothing writes to the database or YouTube now.'

# ---- 4. Row counts, then the final snapshot ------------------------------
$stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
$stage = Join-Path $env:TEMP "midas-move-$stamp"
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$tables = @('channels', 'videos', 'audits', 'interventions', 'lever_verdicts', 'app_users',
            'team_members', 'channel_assignments', 'channel_uploads', 'video_reach_daily')
$parts = $tables | ForEach-Object { "select '$PSItem', count(1) from $PSItem" }
$counts = Sql (($parts -join ' union all ') + ';')
$counts | Set-Content -Encoding ascii -Path (Join-Path $stage 'move-counts.txt')
Say 'Row counts (the Mac checks its restore against these):'
$counts | ForEach-Object { Say "  $PSItem" }

Say 'Publishing the final NAS snapshot. Several GB: this takes a while (10-30 min).'
$snapOut = @()
& docker compose run --rm --no-deps -T midas python -c "import json; from app.backup import snapshot_to_nas; print('SNAPSHOT', json.dumps(snapshot_to_nas()))" 2>&1 |
    ForEach-Object {
        $text = "$PSItem"
        $snapOut += $text
        Write-Host $text
        Add-Content -Encoding utf8 -Path $Log -Value $text
    }
$snapCode = $LASTEXITCODE
$snapLine = $snapOut | Where-Object { $PSItem -like 'SNAPSHOT *' } | Select-Object -Last 1
if ($snapCode -ne 0 -or -not $snapLine -or $snapLine -notmatch '"ok": true') {
    Say 'The snapshot FAILED. Restarting the app here so nothing is lost.'
    Native { docker compose up -d } | Out-Null
    Fail 'Final NAS snapshot failed. This machine is running again; nothing was moved.'
}
Say "Snapshot published: $snapLine"
$snapLine | Set-Content -Encoding ascii -Path (Join-Path $stage 'snapshot.txt')

# ---- 5. Stop everything -------------------------------------------------
$code = Native { docker compose down }
if ($code -ne 0) { Fail 'docker compose down failed (see above). The snapshot is safe on the NAS.' }
Say 'All containers stopped and removed (pgdata, logs, shorts_cache stay on disk).'

# ---- 6. Pack the config for the Mac --------------------------------------
foreach ($f in @('.env', 'docker-compose.yml', 'client_secret.json', 'move-in.sh')) {
    if (Test-Path -LiteralPath $f -PathType Leaf) { Copy-Item -LiteralPath $f -Destination $stage }
}
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'deploy') | Out-Null
Copy-Item -LiteralPath 'deploy\postgrest-proxy.conf' -Destination (Join-Path $stage 'deploy')

$desktop = [Environment]::GetFolderPath('Desktop')
$zip = Join-Path $desktop "midas-move-$stamp.zip"
# tar.exe (built into Windows 10+), not Compress-Archive: PowerShell 5.1's
# Compress-Archive writes backslashes into the zip's paths, which a Mac unpacks
# as flat files named 'deploy\postgrest-proxy.conf'.
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
$code = Native { tar.exe -a -c -f $zip -C $env:TEMP "midas-move-$stamp" }
if ($code -ne 0 -or -not (Test-Path -LiteralPath $zip)) { Fail "Could not write $zip. The files are in $stage; copy that folder to the Mac instead." }
Say "Bundle written: $zip"

# ---- 7. Make sure this machine cannot come back by accident --------------
Rename-Item -LiteralPath '.env' -NewName ".env.moved-$stamp"
Say "Renamed .env to .env.moved-$stamp, so start.bat refuses to run here."

Say ''
Say 'DONE. This machine is no longer running Midas.'
Say ''
Say 'Next:'
Say "  1. Copy $zip to the Mac mini (USB stick or AirDrop; it holds secrets, so keep it off chat if you can)."
Say '  2. On the Mac, unzip it where Midas should live, open Terminal in that folder, run:  bash move-in.sh'
Say '  3. Leave this machine off, or at least never run start.bat here again.'
Say ''
Say "Only if the Mac fails and you need this machine back: rename .env.moved-$stamp to .env and run start.bat."
Say '(pgdata here still holds exactly what the snapshot holds, so no data is lost either way.)'
Read-Host 'Press Enter to close'
