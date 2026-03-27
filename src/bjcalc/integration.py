from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

APP_ID = "org.jako.bjcalc"


def ensure_desktop_entry() -> Path:
    applications_dir = Path.home() / ".local" / "share" / "applications"
    applications_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = applications_dir / f"{APP_ID}.desktop"
    exec_path = Path(sys.argv[0]).resolve()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=bjcalc",
        "Comment=Voice-driven blackjack advisor",
        f"Exec={shlex.quote(str(exec_path))}",
        "Terminal=false",
        "Categories=Utility;",
        "StartupNotify=true",
        f"StartupWMClass={APP_ID}",
        f"X-DBUS-ServiceName={APP_ID}",
    ]
    desktop_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return desktop_path
