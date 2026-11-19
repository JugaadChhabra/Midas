#!/bin/bash
# move-in.sh -- make THIS Mac the Midas host.
#
# Run it from the unzipped midas-move-* folder (made by move-out.ps1 on the old
# machine), in Terminal:
#     bash move-in.sh
# That folder becomes the Midas folder: the database, logs and Shorts cache
# live in it from now on, so put it somewhere permanent first (e.g. ~/midas).
#
# What it does, stopping at the first problem:
#   1. checks the config files, converts Windows line endings
#   2. Apple Silicon: installs Rosetta, pins the app image to linux/amd64
#      (the image is built for amd64 only; it runs emulated)
#   3. installs/starts Docker Desktop if needed
#   4. checks the NAS is reachable (the database restores itself from it)
#   5. pulls the images and starts everything; the app restores the database
#      from the newest NAS snapshot on first boot (can take 30-60+ minutes)
#   6. checks the restored row counts against the old machine's
#   7. stops the Mac from sleeping, restarts it after a power cut, adds
#      Docker to the login items
#
# Everything it prints is also written to logs/move-in.txt.

set -u
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
mkdir -p logs
LOG="$DIR/logs/move-in.txt"
exec > >(tee -a "$LOG") 2>&1

say()  { echo "[$(date +%H:%M:%S)] $*"; }
warn() { echo "[$(date +%H:%M:%S)] WARNING: $*"; }
fail() {
  echo
  say "STOPPED: $*"
  say "Send logs/move-in.txt to Claude."
  exit 1
}

say "Midas move-in (this Mac becomes the host)"
say "========================================="
say "Folder: $DIR"

# ---- 1. Config files --------------------------------------------------------
for f in .env docker-compose.yml client_secret.json; do
  [ -f "$f" ] || fail "Missing $f. Run this from the unzipped midas-move folder."
done
if [ -d deploy/postgrest-proxy.conf ]; then
  # Docker turns a missing bind-mount file into a directory; it can't be mounted.
  rmdir deploy/postgrest-proxy.conf 2>/dev/null
fi
[ -f deploy/postgrest-proxy.conf ] || fail "Missing deploy/postgrest-proxy.conf (a file, not a folder)."

# Files written on Windows carry CRLF line endings; a trailing \r ends up inside
# every .env value (passwords included).
for f in .env docker-compose.yml deploy/postgrest-proxy.conf; do
  if grep -q $'\r' "$f"; then
    cp "$f" "$f.crlf-backup"
    tr -d '\r' < "$f.crlf-backup" > "$f"
    say "Converted Windows line endings in $f (original kept as $f.crlf-backup)."
  fi
done

env_value() { grep -E "^[[:space:]]*$1[[:space:]]*=" .env | tail -1 | cut -d= -f2- | sed -e 's/^[[:space:]"]*//' -e 's/[[:space:]"]*$//'; }

for key in SUPABASE_SERVICE_KEY PGRST_JWT_SECRET POSTGRES_PASSWORD OPENROUTER_API_KEY SESSION_SECRET NAS_SERVER; do
  [ -n "$(env_value "$key")" ] || fail ".env has no value for $key."
done

say "This needs your Mac password once (Rosetta and power settings)."
sudo -v || fail "sudo was refused."

# ---- 2. Apple Silicon -------------------------------------------------------
if [ "$(uname -m)" = "arm64" ]; then
  if ! /usr/bin/pgrep -q oahd; then
    say "Installing Rosetta (runs the amd64 app image)..."
    sudo softwareupdate --install-rosetta --agree-to-license || fail "Rosetta install failed."
  fi
  if ! grep -q 'platform: linux/amd64' docker-compose.yml; then
    cp docker-compose.yml docker-compose.yml.before-platform
    awk '{ print }
         /image: ghcr\.io\/jugaadchhabra\/midas/ && !done {
           match($0, /^ */); printf "%splatform: linux/amd64\n", substr($0, 1, RLENGTH); done = 1 }' \
      docker-compose.yml.before-platform > docker-compose.yml
    grep -q 'platform: linux/amd64' docker-compose.yml || fail "Could not pin the midas image to linux/amd64 in docker-compose.yml."
    say "Pinned the midas service to platform linux/amd64 (the image has no arm64 build)."
  fi
fi

# ---- 3. Docker --------------------------------------------------------------
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin"
if ! command -v docker >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    say "Installing Docker Desktop with Homebrew..."
    brew install --cask docker || fail "brew could not install Docker Desktop."
  else
    fail "Docker is not installed. Install Docker Desktop for Mac (Apple chip) from https://www.docker.com/products/docker-desktop, open it once, then run this again."
  fi
fi
if ! docker info >/dev/null 2>&1; then
  say "Starting Docker Desktop. If it opens a window, accept its terms; this waits up to 5 minutes."
  open -a Docker || fail "Could not open Docker.app."
  for _ in $(seq 1 60); do
    docker info >/dev/null 2>&1 && break
    sleep 5
  done
  docker info >/dev/null 2>&1 || fail "Docker did not come up. Open Docker Desktop, finish its setup, then run this again."
fi
docker compose version >/dev/null 2>&1 || fail "'docker compose' is not available."
say "Docker is running."

# ---- 4. Fresh database, reachable NAS --------------------------------------
if [ -d pgdata ] && [ -n "$(ls -A pgdata 2>/dev/null)" ]; then
  fail "pgdata/ already holds a database, so the NAS restore would be skipped. If it is not wanted: mv pgdata pgdata.old, then run this again."
fi

NAS="$(env_value NAS_SERVER)"
if ! nc -z -G 5 "$NAS" 445 >/dev/null 2>&1; then
  fail "Cannot reach the NAS at $NAS:445. Is this Mac on the office network (cable/Wi-Fi)? On macOS 15+, also allow Terminal and Docker under System Settings > Privacy & Security > Local Network. The app refuses to start without the NAS, by design."
fi
say "NAS $NAS is reachable."

mkdir -p storage/keyframes shorts_cache logs backups

docker compose config -q || fail "docker-compose.yml / .env do not resolve (see above)."

# ---- 5. Pull and start ------------------------------------------------------
say "Pulling images (the app image is several GB the first time)..."
docker compose pull || fail "docker compose pull failed. If it says 'denied' or 'unauthorized', the image needs a GitHub login: docker login ghcr.io"

docker compose up -d || fail "docker compose up failed."
say "Containers started. The app is now restoring the database from the NAS."
say "This is the long part: a 3.7 GB snapshot, run under emulation. Waiting up to 2 hours."

up=0
for i in $(seq 1 240); do
  if curl -sf --max-time 5 http://localhost:8000/health >/dev/null 2>&1; then up=1; break; fi

  restarts="$(docker inspect -f '{{.RestartCount}}' midas 2>/dev/null || echo 0)"
  status="$(docker inspect -f '{{.State.Status}}' midas 2>/dev/null || echo missing)"
  if [ "${restarts:-0}" -gt 0 ] || [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
    # A failed restore must not be retried by the restart policy: a half-
    # restored database would look "populated" on the next boot.
    docker compose stop midas >/dev/null 2>&1
    echo "---- last 80 lines of the app log ----"
    docker compose logs --tail 80 midas
    fail "The app crashed during startup/restore (stopped it so it cannot retry over a half-restored database). After reading the log above: docker compose down && rm -rf pgdata, fix the cause, run this again."
  fi

  if [ $((i % 4)) -eq 0 ]; then
    last="$(docker compose logs --tail 1 --no-log-prefix midas 2>/dev/null | tail -1 | cut -c1-160)"
    say "still starting ($((i / 2)) min): ${last:-no log yet}"
  fi
  sleep 30
done
[ "$up" = 1 ] || fail "The app did not answer /health within 2 hours. Check: docker compose logs --tail 80 midas"
say "The app is up."

# ---- 6. Check the restore ---------------------------------------------------
sql() { docker compose exec -T db psql -U midas midas -tA -F '|' -c "$1"; }

if [ -f move-counts.txt ]; then
  say "Comparing row counts with the old machine:"
  mismatch=0
  while IFS='|' read -r table expected; do
    [ -n "$table" ] || continue
    expected="$(echo "$expected" | tr -d '[:space:]')"
    actual="$(sql "select count(1) from $table;" 2>/dev/null | tr -d '[:space:]')"
    if [ "$actual" = "$expected" ]; then
      say "  ok        $table $actual"
    else
      say "  MISMATCH  $table: old machine $expected, here ${actual:-<error>}"
      mismatch=1
    fi
  done < <(tr -d '\r' < move-counts.txt)
  if [ "$mismatch" = 1 ]; then
    warn "Counts differ. The restore may have used an older snapshot. Do NOT let it run on: docker compose stop midas, then send logs/move-in.txt to Claude."
    exit 1
  fi
  say "Restore matches the old machine exactly."
else
  warn "No move-counts.txt here; skipped the row-count check."
  say "  videos: $(sql 'select count(1) from videos;' | tr -d '[:space:]')  channels: $(sql 'select count(1) from channels;' | tr -d '[:space:]')"
fi

# ---- 7. Keep it running -----------------------------------------------------
if sudo pmset -a sleep 0 disksleep 0 autorestart 1 womp 1; then
  say "Power: never sleeps, restarts by itself after a power cut."
else
  warn "Could not change power settings. Set System Settings > Energy: prevent sleeping, start up after a power failure."
fi

if osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q Docker; then
  say "Docker is already a login item."
elif osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Docker.app", hidden:true}' >/dev/null 2>&1; then
  say "Added Docker to the login items (the containers come back after a reboot)."
else
  warn "Could not add Docker to the login items. In Docker Desktop > Settings > General, tick 'Start Docker Desktop when you sign in'."
fi

# ---- Done -------------------------------------------------------------------
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"
if [ -n "$IP" ] && ! curl -sf --max-time 5 "http://$IP:8000/health" >/dev/null 2>&1; then
  warn "The app answers on localhost but not on $IP. If macOS asked about incoming connections for Docker, allow them (System Settings > Network > Firewall)."
fi

echo
say "DONE. This Mac is the Midas host."
say "  Dashboard here:          http://localhost:8000"
[ -n "$IP" ] && say "  For the team (new URL):  http://$IP:8000   (everyone signs in again)"
say "  Stop / start:            cd \"$DIR\" && docker compose down   /   docker compose up -d"
say "  Live log:                docker compose logs -f midas"
say ""
say "Keep this Mac on and signed in (Docker only runs while a user is logged in)."
say "The nightly NAS backup runs from here from tonight."
