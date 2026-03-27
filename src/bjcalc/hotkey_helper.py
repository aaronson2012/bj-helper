from __future__ import annotations

import argparse
import os
import selectors
import signal
import socket
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices


CTRL_KEYS = {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}
ALT_KEYS = {ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT}
SHIFT_KEYS = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}
MODIFIER_KEYS = {
    "ctrl": CTRL_KEYS,
    "control": CTRL_KEYS,
    "alt": ALT_KEYS,
    "shift": SHIFT_KEYS,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--shortcut", default="Ctrl+Alt+B")
    parser.add_argument("--parent-pid", type=int, required=True)
    return parser.parse_args()


def parse_shortcut(shortcut: str) -> tuple[list[set[int]], int]:
    parts = [part.strip().lower() for part in shortcut.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("Shortcut must include at least one modifier and one key.")

    modifier_groups: list[set[int]] = []
    for token in parts[:-1]:
        keys = MODIFIER_KEYS.get(token)
        if keys is None:
            raise ValueError(f"Unsupported modifier in shortcut: {token}")
        modifier_groups.append(keys)

    final = parts[-1]
    if len(final) == 1 and final.isalpha():
        key_name = f"KEY_{final.upper()}"
    elif len(final) == 1 and final.isdigit():
        key_name = f"KEY_{final}"
    else:
        key_name = f"KEY_{final.upper()}"
    target_key = getattr(ecodes, key_name, None)
    if target_key is None:
        raise ValueError(f"Unsupported shortcut key: {final}")
    return modifier_groups, target_key


def keyboard_device_paths(target_key: int, modifier_groups: list[set[int]]) -> list[str]:
    by_path = sorted(Path("/dev/input/by-path").glob("*-event-kbd"))
    if by_path:
        return [str(path.resolve()) for path in by_path]

    modifier_keys = set().union(*modifier_groups)
    paths: list[str] = []
    for path in list_devices():
        try:
            device = InputDevice(path)
            caps = device.capabilities().get(ecodes.EV_KEY, [])
            if target_key in caps and any(key in caps for key in modifier_keys):
                paths.append(path)
        except OSError:
            continue
    return paths


def send(sock: socket.socket, port: int, message: str) -> None:
    sock.sendto(message.encode("utf-8"), ("127.0.0.1", port))


def main() -> int:
    args = parse_args()
    try:
        modifier_groups, target_key = parse_shortcut(args.shortcut)
    except ValueError as exc:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send(sock, args.port, f"ERROR:{exc}")
        return 1
    devices = []
    for path in keyboard_device_paths(target_key, modifier_groups):
        try:
            devices.append(InputDevice(path))
        except OSError:
            continue

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if not devices:
        send(sock, args.port, "ERROR:No keyboard input device was available for the shortcut helper.")
        return 1

    send(sock, args.port, f"STATUS:Shortcut helper watching {args.shortcut}.")
    selector = selectors.DefaultSelector()
    for device in devices:
        selector.register(device.fd, selectors.EVENT_READ, device)

    pressed: set[int] = set()
    active = False
    running = True

    def handle_signal(_signum: int, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while running:
        try:
            os.kill(args.parent_pid, 0)
        except ProcessLookupError:
            running = False
            break
        for key, _mask in selector.select(timeout=0.25):
            device: InputDevice = key.data
            try:
                for event in device.read():
                    if event.type != ecodes.EV_KEY:
                        continue
                    if event.code not in set().union(*modifier_groups) | {target_key}:
                        continue
                    if event.value in {1, 2}:
                        pressed.add(event.code)
                    elif event.value == 0:
                        pressed.discard(event.code)

                    combo_active = all(any(code in pressed for code in group) for group in modifier_groups) and target_key in pressed

                    if combo_active and not active:
                        active = True
                        send(sock, args.port, "PRESS")
                    elif active and not combo_active:
                        active = False
                        send(sock, args.port, "RELEASE")
            except OSError:
                continue

    if active:
        send(sock, args.port, "RELEASE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
