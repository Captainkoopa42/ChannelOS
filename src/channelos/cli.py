from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loader import load_channel
from .models import ChannelValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channelos",
        description="ChannelOS Phase 0 channel-definition tools.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a channel definition.")
    validate.add_argument("path", type=Path)

    show = sub.add_parser("show", help="Validate and summarize a channel definition.")
    show.add_argument("path", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        channel = load_channel(args.path)
    except ChannelValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        print(f"OK: Channel {channel.display_number} — {channel.name}")
        return 0

    if args.command == "show":
        print(f"Channel {channel.display_number} — {channel.name}")
        if channel.description:
            print(channel.description)
        print(f"Programming: {channel.programming.mode}")
        print(f"Sources: {len(channel.sources)}")
        for source in channel.sources:
            print(f"  - {source.path}")
        return 0

    return 1
