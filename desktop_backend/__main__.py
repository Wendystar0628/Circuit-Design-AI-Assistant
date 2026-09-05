"""Command-line entry point for the local desktop sidecar."""

from __future__ import annotations

import argparse
import re
import sys


_TOKEN_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Circuit Design AI desktop backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--renderer-origin", required=True)
    return parser


def main() -> None:
    if sys.argv[1:2] == ["--simulation-worker"]:
        from domain.simulation.executor.spice_worker import main as worker_main

        worker_main(sys.argv[2:])
        return

    import uvicorn

    from desktop_backend.app import create_app

    args = build_parser().parse_args()
    if args.host not in _LOOPBACK_HOSTS:
        raise SystemExit("--host must be a loopback address")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if not _TOKEN_PATTERN.fullmatch(args.token):
        raise SystemExit("--token must be a 64-character hexadecimal secret")
    host = "127.0.0.1" if args.host == "localhost" else args.host
    uvicorn.run(
        create_app(args.token, args.renderer_origin),
        host=host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
