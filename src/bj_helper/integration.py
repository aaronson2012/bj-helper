from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from bj_helper.debug import log_debug

APP_ID = "org.jako.bj_helper"
LEGACY_APP_ID = "org.jako.bjcalc"
INVALID_APP_ID = "org.jako.bj-helper"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ensure_app_icon() -> Path:
    theme_root = _project_root() / "assets" / "icons" / "hicolor"
    icon_root = Path.home() / ".local" / "share" / "icons" / "hicolor"
    legacy_svg = icon_root / "scalable" / "apps" / "bj-helper.svg"
    legacy_svg.unlink(missing_ok=True)
    preferred_target = icon_root / "64x64" / "apps" / "bj-helper.png"
    copied = 0
    for icon_source in sorted(theme_root.glob("*x*/apps/bj-helper.png")):
        relative_path = icon_source.relative_to(theme_root)
        icon_target = icon_root / relative_path
        icon_target.parent.mkdir(parents=True, exist_ok=True)
        if not icon_target.exists() or icon_target.read_bytes() != icon_source.read_bytes():
            shutil.copyfile(icon_source, icon_target)
            copied += 1
    log_debug("integration_app_icon_ready", preferred_target=str(preferred_target), copied=copied)
    return preferred_target


def ensure_desktop_entry() -> Path:
    applications_dir = Path.home() / ".local" / "share" / "applications"
    applications_dir.mkdir(parents=True, exist_ok=True)
    legacy_desktop_path = applications_dir / f"{LEGACY_APP_ID}.desktop"
    legacy_desktop_path.unlink(missing_ok=True)
    invalid_desktop_path = applications_dir / f"{INVALID_APP_ID}.desktop"
    invalid_desktop_path.unlink(missing_ok=True)
    desktop_path = applications_dir / f"{APP_ID}.desktop"
    ensure_app_icon()
    launcher = shlex.quote(str(_project_root() / "run-bj-helper"))
    exec_command = launcher
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=bj-helper",
        "Comment=Voice-driven blackjack advisor",
        "Icon=bj-helper",
        f"Exec={exec_command}",
        "Terminal=false",
        "Categories=Utility;",
        "StartupNotify=true",
        f"StartupWMClass={APP_ID}",
        f"X-DBUS-ServiceName={APP_ID}",
    ]
    desktop_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_debug("integration_desktop_entry_ready", desktop_path=str(desktop_path), exec_command=exec_command)
    return desktop_path
