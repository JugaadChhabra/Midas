#!/bin/bash
# Stop Midas.
# Usage: ./stop.sh
#
# `docker compose down` stops and removes the containers but leaves the host
# bind mounts (storage/ shorts_cache/ logs/) untouched — job artifacts and logs
# stay on disk so you can recover an upload that failed on a quota hit.

echo "Stopping Midas..."
docker compose down
echo "✅ Service stopped"
echo ""
echo "Job artifacts and logs are kept on the host:"
echo "  ./shorts_cache   (cut videos awaiting upload)"
echo "  ./storage        (keyframes / working data)"
echo "  ./logs           (midas.log)"
