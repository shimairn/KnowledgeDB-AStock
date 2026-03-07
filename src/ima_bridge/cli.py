from __future__ import annotations

import argparse
import json
import sys

from ima_bridge.config import get_settings
from ima_bridge.service import IMAAskService

DEFAULT_QUESTION = "\u8bf7\u7528\u4e00\u53e5\u8bdd\u4ecb\u7ecd\u8fd9\u4e2a\u77e5\u8bc6\u5e93\u3002"
EXIT_WORDS = {"exit", "quit", ":q"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ima_bridge")
    parser.add_argument("--instance", default="default")
    parser.add_argument("--driver", choices=["web", "app"], default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--profile-dir", default=None)
    parser.add_argument("--headed", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("health")
    login = subparsers.add_parser("login")
    login.add_argument("--timeout", type=float, default=None)

    ask = subparsers.add_parser("ask")
    ask.add_argument("--question", default=DEFAULT_QUESTION)

    start = subparsers.add_parser("start")
    start.add_argument("--question", default=None)
    start.add_argument("--login-timeout", type=float, default=180.0)
    start.add_argument("--no-auto-login", action="store_true")
    return parser


def print_json(payload) -> None:
    print(json.dumps(payload.model_dump(), ensure_ascii=False, indent=2))


def run_start(service: IMAAskService, args: argparse.Namespace) -> int:
    health = service.health()
    print_json(health)

    if not health.ok:
        if (
            health.source_driver == "web"
            and health.error_code == "LOGIN_REQUIRED"
            and not args.no_auto_login
        ):
            login = service.login(timeout_seconds=args.login_timeout)
            print_json(login)
            if not login.ok:
                return 1
            health = service.health()
            print_json(health)
            if not health.ok:
                return 1
        else:
            return 1

    if args.question:
        result = service.ask(args.question)
        print_json(result)
        return 0 if result.ok else 1

    print('ready: ask questions now, type "exit" to quit')
    while True:
        try:
            question = input("ima> ").strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            break

        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            break
        if question.lower() == ":health":
            print_json(service.health())
            continue

        result = service.ask(question)
        print_json(result)

    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    if args.command not in {"health", "ask", "login", "start"}:
        parser.print_help()
        return 1

    settings = get_settings(
        instance=args.instance,
        port=args.port,
        profile_dir=args.profile_dir,
        driver_mode=args.driver,
        web_headless=False if args.headed else None,
    )
    service = IMAAskService(settings=settings)
    if args.command == "health":
        result = service.health()
        print_json(result)
        return 0 if result.ok else 1
    elif args.command == "login":
        result = service.login(timeout_seconds=args.timeout)
        print_json(result)
        return 0 if result.ok else 1
    elif args.command == "start":
        return run_start(service, args)
    else:
        result = service.ask(args.question)
        print_json(result)
    return 0 if result.ok else 1
