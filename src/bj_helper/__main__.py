from __future__ import annotations

import sys

from bj_helper.app import run_app
from bj_helper.control import ping_server, send_start_listening


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["is-running"], ["--is-running"]):
        return 0 if ping_server() else 1
    if args in (["start-listening"], ["--start-listening"]):
        if send_start_listening():
            return 0
        print("No running bj-helper instance responded to start-listening.", file=sys.stderr)
        return 1
    if args:
        print("Usage: python -m bj_helper [is-running|start-listening]", file=sys.stderr)
        return 2
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
