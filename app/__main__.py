"""Command-line entry point for the ClaudeMicro tray application."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence


def _port(value: str) -> int:
    """Parse a TCP port, including zero for an OS-assigned free port."""
    try:
        port = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Run the ClaudeMicro bridge as a macOS tray application.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        help=(
            "loopback port for the embedded bridge "
            "(overrides CLAUDEMICRO_PORT; default: 35703)"
        ),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="start on an OS-assigned port, verify HTTP, and exit without GUI imports",
    )
    return parser


def _requested_port(
    parser: argparse.ArgumentParser,
    cli_port: int | None,
    *,
    smoke: bool,
    default: int,
) -> int:
    if smoke:
        # Smoke mode must never collide with a normally running bridge.
        return 0
    if cli_port is not None:
        return cli_port
    env_port = os.environ.get("CLAUDEMICRO_PORT")
    if env_port is None or not env_port.strip():
        return default
    try:
        return _port(env_port.strip())
    except argparse.ArgumentTypeError as exc:
        parser.error(f"invalid CLAUDEMICRO_PORT: {exc}")
        raise AssertionError("argparse.error always exits") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    # app.tray imports aiohttp/server code, but it still does not import any GUI
    # package. Keeping this import after parsing also makes --help maximally light.
    from app import tray

    try:
        if args.smoke:
            tray.run_smoke()
        else:
            requested_port = _requested_port(
                parser,
                args.port,
                smoke=False,
                default=tray.SERVER_DEFAULT_PORT,
            )
            tray.run_tray_app(requested_port)
    except tray.AppError as exc:
        print(f"ClaudeMicro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ClaudeMicro: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
