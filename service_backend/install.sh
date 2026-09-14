#!/usr/bin/env bash
set -euo pipefail

# Install the update service on a small Linux server without third-party
# Python dependencies. Run from the extracted service_backend directory.
INSTALL_DIR="${TIMETIP_INSTALL_DIR:-/opt/timetip-update-service}"
DATA_DIR="${TIMETIP_UPDATE_ROOT:-/var/lib/timetip-updates}"
PORT="${TIMETIP_PORT:-8787}"
mkdir -p "$INSTALL_DIR" "$DATA_DIR"
cp server.py README.md update.json.example "$INSTALL_DIR/"
cat > /etc/systemd/system/timetip-update.service <<UNIT
[Unit]
Description=TimeTip update service
After=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/server.py
Environment=TIMETIP_UPDATE_ROOT=$DATA_DIR
Environment=TIMETIP_PUBLIC_BASE_URL=http://47.116.193.23:$PORT
Environment=TIMETIP_REPO_URL=https://github.com/BigSheep261/Time-Tip.git
Environment=TIMETIP_RELEASE_BRANCH=release
Environment=TIMETIP_PORT=$PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now timetip-update.service
echo "TimeTip update service installed: http://47.116.193.23:$PORT/admin"
