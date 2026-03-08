from __future__ import annotations

import argparse
import json
import sys

from ima_bridge.chat_ui import run_chat_ui
from ima_bridge.config import get_settings
from ima_bridge.probes import APP_DRIVER_DEPRECATION_MESSAGE
from ima_bridge.service import IMAAskService
from ima_bridge.worker_pool import WorkerPoolManager

DEFAULT_QUESTION = "\u8bf7\u7528\u4e00\u53e5\u8bdd\u4ecb\u7ecd\u8fd9\u4e2a\u77e5\u8bc6\u5e93\u3002"
EXIT_WORDS = {"exit", "quit", ":q"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ima_bridge")
    parser.add_argument("--instance", default="default")
    parser.add_argument("--driver", choices=["web", "app"], default=None, help="driver mode; app is deprecated")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--profile-dir", default=None)
    parser.add_argument("--headed", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("health")

    login = subparsers.add_parser("login")
    login.add_argument("--timeout", type=float, default=None)

    login_pool = subparsers.add_parser("login-pool")
    login_pool.add_argument("--workers", type=int, default=None)
    login_pool.add_argument("--timeout", type=float, default=None)

    ask = subparsers.add_parser("ask")
    ask.add_argument("--question", default=DEFAULT_QUESTION)

    start = subparsers.add_parser("start")
    start.add_argument("--question", default=None)
    start.add_argument("--login-timeout", type=float, default=180.0)
    start.add_argument("--no-auto-login", action="store_true")

    ui = subparsers.add_parser("ui")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--ui-port", type=int, default=8765)
    ui.add_argument("--workers", type=int, default=None)
    ui.add_argument("--no-open", action="store_true")
    return parser


def print_json(payload) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def warn_if_deprecated_driver(driver_mode: str) -> None:
    if driver_mode == "app":
        print(f"warning: {APP_DRIVER_DEPRECATION_MESSAGE}", file=sys.stderr)


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


def run_login_pool(settings, args: argparse.Namespace) -> int:
    if settings.driver_mode != "web":
        print("login-pool only supports --driver web", file=sys.stderr)
        return 2

    worker_count = args.workers if args.workers is not None else settings.ui_worker_count
    pool_manager = WorkerPoolManager(template_settings=settings, worker_count=worker_count)

    results: list[dict] = []
    all_ok = True
    for worker in pool_manager.iter_login_services():
        result = worker.service.login(timeout_seconds=args.timeout)
        pool_manager.refresh_worker(worker)
        payload = result.model_dump()
        payload["worker_id"] = worker.worker_id
        payload["worker_status"] = worker.status
        results.append(payload)
        if not result.ok:
            all_ok = False

    print_json(
        {
            "ok": all_ok,
            "workers_total": worker_count,
            "workers": results,
        }
    )
    return 0 if all_ok else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    if args.command not in {"health", "ask", "login", "login-pool", "start", "ui"}:
        parser.print_help()
        return 1

    settings = get_settings(
        instance=args.instance,
        port=args.port,
        profile_dir=args.profile_dir,
        driver_mode=args.driver,
        web_headless=False if args.headed else None,
    )
    warn_if_deprecated_driver(settings.driver_mode)

    if args.command == "login-pool":
        return run_login_pool(settings, args)

    service = IMAAskService(settings=settings)
    if args.command == "health":
        result = service.health()
        print_json(result)
        return 0 if result.ok else 1
    if args.command == "login":
        result = service.login(timeout_seconds=args.timeout)
        print_json(result)
        return 0 if result.ok else 1
    if args.command == "start":
        return run_start(service, args)
    if args.command == "ui":
        return run_chat_ui(
            service=service,
            host=args.host,
            port=args.ui_port,
            open_browser=not args.no_open,
            workers=args.workers,
        )

    result = service.ask(args.question)
    print_json(result)
    return 0 if result.ok else 1
