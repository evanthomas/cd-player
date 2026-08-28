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

# If / is overlay-protected (Raspberry Pi OS's overlayroot -- see CLAUDE.md),
# a plain cp/tee/ln under /etc only lands in the overlay's tmpfs upper
# layer and silently reverts on the next reboot. overlayroot-chroot remounts
# the real underlying filesystem read-write and runs one command against
# it instead, with no reboot needed for the write itself to stick.
is_overlay_active() {
  mount | grep -q "^overlayroot on / "
}

# Calling overlayroot-chroot more than once tends to print
# "mount: /media/root-ro: mount point is busy" from its own cleanup step
# (it can't remount the lowerdir back to read-only while the live overlay
# still references it) -- harmless noise, not a failure: the command run
# inside the chroot has already completed and taken effect by that point,
# and the flag corrects itself on the next reboot regardless.

persistent_write() {  # persistent_write <dest-path>, content from stdin
  if is_overlay_active; then
    sudo overlayroot-chroot tee "$1" > /dev/null
  else
    sudo tee "$1" > /dev/null
  fi
}

persistent_symlink() {  # persistent_symlink <target> <link-path>
  if is_overlay_active; then
    sudo overlayroot-chroot ln -sf "$1" "$2"
  else
    sudo ln -sf "$1" "$2"
  fi
}

echo "==> Installing systemd unit files"
cat deploy/cd-player.service | persistent_write /etc/systemd/system/cd-player.service
cat deploy/cd-player-ui.service | persistent_write /etc/systemd/system/cd-player-ui.service

if [ ! -f /etc/default/cd-player ]; then
  echo "==> Creating /etc/default/cd-player from the template"
  cat deploy/cd-player.env.example | persistent_write /etc/default/cd-player
  echo "    Edit it to set your speaker name / advertise host / device path,"
  echo "    then: sudo systemctl restart cd-player"
else
  echo "==> /etc/default/cd-player already exists, leaving it as-is"
fi

echo "==> Enabling services to start at boot"
persistent_symlink /etc/systemd/system/cd-player.service /etc/systemd/system/multi-user.target.wants/cd-player.service
persistent_symlink /etc/systemd/system/cd-player-ui.service /etc/systemd/system/multi-user.target.wants/cd-player-ui.service

echo "==> Reloading systemd and starting services"
sudo systemctl daemon-reload
sudo systemctl restart cd-player.service
sudo systemctl restart cd-player-ui.service

echo
echo "Done. Useful commands:"
echo "  systemctl status cd-player cd-player-ui"
echo "  journalctl -u cd-player -f"
echo "  journalctl -u cd-player-ui -f"
