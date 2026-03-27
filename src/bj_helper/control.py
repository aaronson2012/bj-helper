from __future__ import annotations

import os
from collections.abc import Callable
from enum import StrEnum

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from bj_helper.debug import log_debug


START_LISTENING_COMMAND = "start-listening"
PING_COMMAND = "ping"
_BASE_SERVER_NAME = "org.jako.bj_helper.control"


class ControlServerStatus(StrEnum):
    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    FAILED = "failed"


def _server_name() -> str:
    if hasattr(os, "getuid"):
        return f"{_BASE_SERVER_NAME}.{os.getuid()}"
    username = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"{_BASE_SERVER_NAME}.{username}"


class ControlServer(QObject):
    def __init__(self, on_start_listening: Callable[[], None]) -> None:
        super().__init__()
        self._on_start_listening = on_start_listening
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_new_connections)
        self._name = _server_name()

    def start(self) -> ControlServerStatus:
        if self._server.listen(self._name):
            log_debug("control_server_started", name=self._name)
            return ControlServerStatus.STARTED
        if ping_server():
            log_debug("control_server_already_running", name=self._name)
            return ControlServerStatus.ALREADY_RUNNING
        QLocalServer.removeServer(self._name)
        if self._server.listen(self._name):
            log_debug("control_server_recovered_stale_socket", name=self._name)
            return ControlServerStatus.STARTED
        log_debug("control_server_start_failed", name=self._name, error=self._server.errorString())
        return ControlServerStatus.FAILED

    def stop(self) -> None:
        if self._server.isListening():
            self._server.close()
            QLocalServer.removeServer(self._name)
            log_debug("control_server_stopped", name=self._name)

    def _handle_new_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                break
            socket.readyRead.connect(lambda sock=socket: self._handle_socket(sock))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._handle_socket(socket)

    def _handle_socket(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
        log_debug("control_server_command", payload=payload)
        if payload == START_LISTENING_COMMAND:
            self._on_start_listening()
            socket.write(b"ok\n")
        elif payload == PING_COMMAND:
            socket.write(b"pong\n")
        else:
            socket.write(b"error\n")
        socket.flush()
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()


def send_command(command: str, timeout_ms: int = 1500) -> str | None:
    socket = QLocalSocket()
    socket.connectToServer(_server_name())
    if not socket.waitForConnected(timeout_ms):
        log_debug("control_client_connect_failed", name=_server_name(), error=socket.errorString())
        return None
    socket.write((command + "\n").encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.waitForReadyRead(timeout_ms)
    payload = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
    socket.disconnectFromServer()
    log_debug("control_client_command_sent", payload=command, response=payload)
    return payload or None


def send_start_listening(timeout_ms: int = 1500) -> bool:
    return send_command(START_LISTENING_COMMAND, timeout_ms=timeout_ms) == "ok"


def ping_server(timeout_ms: int = 250) -> bool:
    return send_command(PING_COMMAND, timeout_ms=timeout_ms) == "pong"
