from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QSocketNotifier, QTimer, pyqtSignal


class GlobalShortcutManager(QObject):
    activated = pyqtSignal()
    deactivated = pyqtSignal()
    status_changed = pyqtSignal(str)

    def __init__(self, shortcut: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shortcut = shortcut
        runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
        self._pidfile = runtime_dir / "bjcalc-hotkey-helper.pid"
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.setblocking(False)
        self._port = self._sock.getsockname()[1]
        self._notifier = QSocketNotifier(self._sock.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._drain_messages)
        self._process: subprocess.Popen[bytes] | None = None
        self._closing = False
        self._monitor = QTimer(self)
        self._monitor.setInterval(1000)
        self._monitor.timeout.connect(self._check_process)

    @property
    def available(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def register(self) -> None:
        if self.available:
            return
        self._closing = False
        self._cleanup_stale_helper()
        python_exec = shlex.quote(sys.executable)
        shortcut = shlex.quote(self._shortcut)
        helper_command = (
            f"sudo {python_exec} -m bjcalc.hotkey_helper --port {self._port} "
            f"--shortcut {shortcut} --parent-pid {os.getpid()}"
        )
        command = ["script", "-qfc", helper_command, "/dev/null"]
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        self._pidfile.write_text(str(self._process.pid), encoding="utf-8")
        self._monitor.start()
        self.status_changed.emit(f"Starting global push-to-talk shortcut: {self._shortcut}")

    def close(self) -> None:
        self._closing = True
        self._monitor.stop()
        if self._process is not None and self._process.poll() is None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self._pidfile.exists():
            self._pidfile.unlink(missing_ok=True)
        self._process = None
        self._notifier.setEnabled(False)
        self._sock.close()

    def _drain_messages(self) -> None:
        while True:
            try:
                payload, _addr = self._sock.recvfrom(4096)
            except BlockingIOError:
                return
            message = payload.decode("utf-8", "replace").strip()
            if not message:
                continue
            if message == "PRESS":
                self.activated.emit()
            elif message == "RELEASE":
                self.deactivated.emit()
            elif message.startswith("STATUS:"):
                self.status_changed.emit(message.removeprefix("STATUS:").strip())
            elif message.startswith("ERROR:"):
                self.status_changed.emit(message.removeprefix("ERROR:").strip())

    def _check_process(self) -> None:
        if self._process is None:
            self._monitor.stop()
            return
        return_code = self._process.poll()
        if return_code is None:
            return
        self._monitor.stop()
        stderr_text = ""
        if self._process.stderr is not None:
            stderr_text = self._process.stderr.read().decode("utf-8", "replace").strip()
        self._process = None
        detail = f" (exit {return_code})" if return_code else ""
        if stderr_text:
            self.status_changed.emit(f"Shortcut helper stopped{detail}: {stderr_text}")
        else:
            self.status_changed.emit(f"Shortcut helper stopped{detail}.")
        if self._pidfile.exists():
            self._pidfile.unlink(missing_ok=True)
        if not self._closing:
            self.status_changed.emit("Restarting global push-to-talk shortcut.")
            QTimer.singleShot(1000, self.register)

    def _cleanup_stale_helper(self) -> None:
        if not self._pidfile.exists():
            return
        try:
            pid = int(self._pidfile.read_text(encoding="utf-8").strip())
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError, ValueError):
            pass
        self._pidfile.unlink(missing_ok=True)
