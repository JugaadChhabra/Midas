#!/bin/bash
# Quick start script for Midas (GHCR image).
# Usage: ./start.sh
#
# Brings up midas + the bgutil PO-token sidecar via docker compose, after
# checking that .env, client_secret.json, and the required keys are present.
# Creates the host-mounted job folders (storage/ shorts_cache/ logs/) so a run
# that dies on a YouTube quota hit still leaves its artifacts and log on disk.

set -e

echo "Midas Quick Start"
echo "================="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install from https://www.docker.com/products/docker-desktop"
    exit 1
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "No .env found."
    if [ -f .env.example ]; then
        echo "Copy the template and fill it in:"
        echo "  cp .env.example .env"
    fi
    echo "Then run this script again."
    exit 1
fi

# client_secret.json is bind-mounted read-only into the container for OAuth.
if [ ! -f client_secret.json ]; then
    echo "Missing client_secret.json (Google OAuth client). Place it here, then re-run."
    exit 1
fi

required_keys=(
  "SUPABASE_URL"
  "SUPABASE_SERVICE_KEY"
  "OPENROUTER_API_KEY"
  "SESSION_SECRET"
)

missing=()
for key in "${required_keys[@]}"; do
  if ! grep -Eq "^[[:space:]]*${key}[[:space:]]*=[[:space:]]*.+$" .env; then
    missing+=("${key}")
  fi
done

if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing required keys in .env:"
  for key in "${missing[@]}"; do
    echo "  - ${key}"
  done
  exit 1
fi

echo "Config looks good."
echo ""

# Create host-mounted job folders (match the bind mounts in docker-compose.yml).
mkdir -p storage/keyframes shorts_cache logs
echo "Ready host folders: storage, shorts_cache, logs"

echo ""
echo "Starting Midas (pulls the latest images automatically)..."
docker compose up -d

# Wait for service to be ready
echo "Waiting for service to start..."
sleep 5

# Check health (midas serves on :8000)
if curl -s http://localhost:8000/health > /dev/null; then
    echo "Service is healthy."
    echo ""
    echo "Midas is running."
    echo ""
    echo "Open your browser: http://localhost:8000"
else
    echo "Service started but may still be initializing (first run + PO-token warmup can take a minute)."
    echo "Check status: docker compose logs -f"
fi

echo ""
echo "Live logs (host):  tail -f logs/midas.log"
echo "Container logs:    docker compose logs -f midas"
echo "Job artifacts:     ./shorts_cache/<channel>/tmp"
echo "To stop:           ./stop.sh"
