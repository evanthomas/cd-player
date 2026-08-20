"""Physical drive control -- currently just opening the tray, via the
`eject` CLI (same shell-out style as `cdparanoia` in ripper.py).
"""

from __future__ import annotations

import subprocess


def eject_tray(device_path: str) -> None:
    subprocess.run(["eject", device_path], check=True)
