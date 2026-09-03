#!/usr/bin/env bash
#
# Install the Control Agent so it runs on power-on (Jetson HOST).
#
# HOW TO RUN (on the Jetson host, dk@jetson:~$):
#   1) Pull the deploy files out of the container to the host:
#        docker cp iot-2708:/ultralytics/workspace/iot-challenge-2025/khang-jetson/projects/local_server/deploy /tmp/shelf-deploy
#   2) Run this installer as root:
#        sudo bash /tmp/shelf-deploy/setup-control-agent.sh
#
# After this: on every power-on the health/start panel is available at
#   http://<jetson-ip>:8088   (join the shelf hotspot, open in a browser)
# The vending app (main.py) does NOT auto-run — you press START on the panel.
#
# Safe to re-run.

set -e
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/shelf-control"

echo "=== Installing Smart Shelf Control Agent ==="

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root:  sudo bash $0"
    exit 1
fi

echo "[1/4] Copying agent to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp "$SRC_DIR/control_agent.py" "$INSTALL_DIR/control_agent.py"

echo "[2/4] Installing systemd service ..."
cp "$SRC_DIR/control-agent.service" /etc/systemd/system/control-agent.service
systemctl daemon-reload

echo "[3/4] Enabling on boot + starting now ..."
systemctl enable control-agent.service
systemctl restart control-agent.service

echo "[4/4] Making sure the vending container does NOT auto-run the app ..."
# The container may still exist; we only ensure Docker itself starts on boot.
# The Control Agent decides when to launch main.py, so we do NOT set the
# container to auto-run main.py here.
systemctl enable docker >/dev/null 2>&1 || true

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "=== Done ==="
echo "Health + control panel:  http://${IP:-<jetson-ip>}:8088"
echo "Check it is running:      systemctl status control-agent --no-pager"
echo "View its logs:            journalctl -u control-agent -f"
