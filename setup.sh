#!/usr/bin/env bash
# Installs everything needed to run cd-player: system packages, the Python
# virtual environment, and (with --ui) the touchscreen UI's dependencies,
# including building pygame from source against the system SDL2 so it has
# KMSDRM support (the PyPI wheel doesn't -- see CLAUDE.md).
#
# Usage:
#   ./setup.sh                        base install (cd-player only)
#   ./setup.sh --ui                   also install cd-player-ui's dependencies
#   ./setup.sh --ui --force-pygame    rebuild pygame even if already installed
#
# Safe to re-run: apt/pip installs are idempotent, and the pygame source
# build (the slow step) is skipped if pygame is already importable in .venv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

with_ui=0
force_pygame=0
for arg in "$@"; do
  case "$arg" in
    --ui) with_ui=1 ;;
    --force-pygame) force_pygame=1 ;;
    -h|--help)
      sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--ui] [--force-pygame]" >&2
      exit 1
      ;;
  esac
done

echo "==> Installing system dependencies"
system_packages=(cdparanoia libdiscid0 python3-venv)
if [ "$with_ui" -eq 1 ]; then
  system_packages+=(python3-dev libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev libsdl2-mixer-dev)
fi
sudo apt-get update
sudo apt-get install -y "${system_packages[@]}"

echo "==> Creating virtual environment (.venv)"
if [ ! -d .venv ]; then
  python3 -m venv .venv
else
  echo "    .venv already exists, reusing it"
fi

echo "==> Upgrading pip"
.venv/bin/pip install --upgrade pip

echo "==> Installing cd-player (with dev extras)"
.venv/bin/pip install -e ".[dev]"

if [ "$with_ui" -eq 1 ]; then
  if [ "$force_pygame" -eq 0 ] && .venv/bin/python -c "import pygame" 2>/dev/null; then
    echo "==> pygame already installed, skipping rebuild (use --force-pygame to rebuild)"
  else
    echo "==> Building pygame from source against system SDL2 (KMSDRM support) -- this takes a minute or two"
    .venv/bin/pip install --no-binary pygame -e ".[ui]"
  fi
fi

echo
echo "Done."
echo "  Run the server:     .venv/bin/cd-player --help"
if [ "$with_ui" -eq 1 ]; then
  echo "  Run the touchscreen: .venv/bin/cd-player-ui --help"
fi
