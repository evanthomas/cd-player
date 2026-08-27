#!/usr/bin/env bash
# Installs cd-player and cd-player-ui as systemd services that start at
# boot, waiting for network and pulling the latest code from this repo's
# git remote first (see deploy/cd-player-boot.sh).
#
# Run ./setup.sh (--ui) first to create .venv. Safe to re-run: an existing
# /etc/default/cd-player is never overwritten, unit files are just
# replaced and reloaded.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -x .venv/bin/cd-player ] || [ ! -x .venv/bin/cd-player-ui ]; then
  echo "error: .venv/bin/cd-player(-ui) not found -- run ./setup.sh --ui first" >&2
  exit 1
fi

chmod +x deploy/cd-player-boot.sh

echo "==> Installing systemd unit files"
sudo cp deploy/cd-player.service deploy/cd-player-ui.service /etc/systemd/system/

if [ ! -f /etc/default/cd-player ]; then
  echo "==> Creating /etc/default/cd-player from the template"
  sudo cp deploy/cd-player.env.example /etc/default/cd-player
  echo "    Edit it to set your speaker name / advertise host / device path,"
  echo "    then: sudo systemctl restart cd-player"
else
  echo "==> /etc/default/cd-player already exists, leaving it as-is"
fi

echo "==> Reloading systemd and enabling services"
sudo systemctl daemon-reload
sudo systemctl enable --now cd-player.service
sudo systemctl enable --now cd-player-ui.service

echo
echo "Done. Useful commands:"
echo "  systemctl status cd-player cd-player-ui"
echo "  journalctl -u cd-player -f"
echo "  journalctl -u cd-player-ui -f"
