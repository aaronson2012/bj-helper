from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from secrets import token_hex


_LOCK = threading.Lock()
_SESSION_ID = token_hex(4)


def log_debug(event: str, **fields: object) -> None:
    path = _debug_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="milliseconds")
    payload = " ".join(f"{key}={_format(value)}" for key, value in sorted(fields.items()))
    line = f"{timestamp} session={_SESSION_ID} pid={os.getpid()} tid={threading.get_ident()} {event}"
    if payload:
        line += f" {payload}"
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def debug_log_path() -> Path | None:
    return _debug_path()


def _debug_path() -> Path | None:
    path_text = os.environ.get("BJ_HELPER_DEBUG_LOG", "").strip()
    if path_text:
        return Path(path_text).expanduser()
    if os.environ.get("BJ_HELPER_DEBUG", "1").strip().lower() in {"0", "false", "no", "off"}:
        return None
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "bj-helper" / "debug.log"


def _format(value: object) -> str:
    return repr(value).replace("\n", "\\n")
