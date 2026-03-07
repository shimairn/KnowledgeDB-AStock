from __future__ import annotations

import argparse
import json

import uvicorn

from ima_bridge.api import create_app
from ima_bridge.service import IMABridgeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ima_bridge")
    subparsers = parser.add_subparsers(dest="command")

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--question", default=None)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    parser.add_argument("--question", default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0

    service = IMABridgeService()
    question = args.question or service.settings.default_question
    response = service.ask_once(question)
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))
    return 0 if response.ok else 1
