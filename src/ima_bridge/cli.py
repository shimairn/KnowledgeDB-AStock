from __future__ import annotations

import argparse
import json
import sys

from ima_bridge.config import get_settings
from ima_bridge.service import IMAAskService

DEFAULT_QUESTION = "\u8bf7\u7528\u4e00\u53e5\u8bdd\u4ecb\u7ecd\u8fd9\u4e2a\u77e5\u8bc6\u5e93\u3002"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ima_bridge")
    parser.add_argument("--instance", default="default")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--profile-dir", default=None)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("health")
    ask = subparsers.add_parser("ask")
    ask.add_argument("--question", default=DEFAULT_QUESTION)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    if args.command not in {"health", "ask"}:
        parser.print_help()
        return 1

    settings = get_settings(instance=args.instance, port=args.port, profile_dir=args.profile_dir)
    service = IMAAskService(settings=settings)
    result = service.health() if args.command == "health" else service.ask(args.question)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1
