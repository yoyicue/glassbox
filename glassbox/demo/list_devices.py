"""glassbox/demo/list_devices.py — list all AVFoundation devices

How to run:
    python -m glassbox.demo.list_devices
    # or after installing the package:
    glassbox-list-devices
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from glassbox.perception.source import list_avfoundation_devices


def main() -> int:
    console = Console()
    devices = list_avfoundation_devices()
    if not devices:
        console.print("[red]no device found (or ffmpeg not installed)[/red]")
        console.print("brew install ffmpeg")
        return 1

    table = Table(title="AVFoundation video devices")
    table.add_column("index", style="cyan", justify="right")
    table.add_column("name", style="white")
    table.add_column("hint", style="yellow")
    for d in devices:
        hint = ""
        name_lower = d["name"].lower()
        if any(k in name_lower for k in ("facetime", "iphone", "camera")):
            hint = "(built-in / iPhone screen mirror, not a capture card)"
        elif any(k in name_lower for k in ("hdmi", "elgato", "cam link", "magewell", "uvc")):
            hint = "★ likely an HDMI capture card"
        table.add_row(str(d["index"]), d["name"], hint)
    console.print(table)
    console.print()
    console.print("usage: [cyan]AVFFrameSource(device_index=<index>)[/cyan]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
