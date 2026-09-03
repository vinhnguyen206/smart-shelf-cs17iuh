#!/usr/bin/env bash
#
# One-time setup so the Smart Shelf runs on power-on with NO commands.
#
# Run this ONCE on the Jetson HOST (not inside the container):
#   dk@jetson:~$  bash setup-autostart.sh
#
# After this: plug in power -> wait ~3 min -> the shelf is running.
# No SSH, no docker, no python3 typing ever again for normal use.
#
# It is safe to re-run (idempotent). It does NOT change any app code.

set -e

CONTAINER="iot-2708"

echo "=== Smart Shelf auto-start setup ==="

# 1) Make sure the Docker daemon itself starts on boot
echo "[1/3] Enabling Docker service on boot..."
sudo systemctl enable docker >/dev/null 2>&1 || true

# 2) Tell Docker to always bring this container back up:
#    - on reboot / power-on
#    - if it ever crashes
#    'unless-stopped' = auto-start always, EXCEPT if you deliberately
#    'docker stop' it (so you can still stop it by hand when needed).
echo "[2/3] Setting restart policy on '$CONTAINER'..."
if sudo docker inspect "$CONTAINER" >/dev/null 2>&1; then
    sudo docker update --restart unless-stopped "$CONTAINER"
else
    echo "  !! Container '$CONTAINER' not found. Start it once, then re-run this."
    exit 1
fi

# 3) Start it now so it's running immediately (and confirm)
echo "[3/3] Starting '$CONTAINER' now..."
sudo docker start "$CONTAINER" >/dev/null 2>&1 || true

echo ""
echo "=== Done ==="
echo "From now on: plug in power, wait ~3 minutes, the shelf runs by itself."
echo ""
echo "Useful commands (only if you ever need them):"
echo "  Watch logs:   docker logs -f $CONTAINER 2>&1 | grep --line-buffered Loadcell"
echo "  Restart app:  docker restart $CONTAINER"
echo "  Stop for good until next manual start:  docker stop $CONTAINER"
