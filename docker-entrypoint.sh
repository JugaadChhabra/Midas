#!/bin/sh
# Refresh yt-dlp on every container start so shorts downloads survive YouTube's
# frequent server-side extractor changes WITHOUT waiting for the next image
# rebuild — the box self-heals just by restarting (i.e. by re-running start).
#
# Best-effort by design: if the host is offline at boot or PyPI is unreachable,
# log it and boot anyway on the version baked into the image. Never block startup
# on the network. The weekly image rebuild (see Dockerfile / docker-publish.yml)
# is the backstop so even an always-offline box stays reasonably current.
set -e

echo "[entrypoint] refreshing yt-dlp (best-effort)..."
if python -m pip install --no-cache-dir -U --pre "yt-dlp[default]" >/tmp/ytdlp-update.log 2>&1; then
    echo "[entrypoint] yt-dlp now: $(yt-dlp --version 2>/dev/null || echo unknown)"
else
    echo "[entrypoint] yt-dlp refresh failed (offline / PyPI unreachable) — using baked-in $(yt-dlp --version 2>/dev/null || echo unknown)"
    tail -n 3 /tmp/ytdlp-update.log 2>/dev/null || true
fi

exec "$@"
