from __future__ import annotations

from ima_bridge.cli import DEFAULT_QUESTION, build_parser


def test_cli_parses_health():
    parser = build_parser()
    args = parser.parse_args(["--instance", "win2", "--driver", "web", "--port", "9330", "--headed", "health"])
    assert args.command == "health"
    assert args.instance == "win2"
    assert args.driver == "web"
    assert args.port == 9330
    assert args.headed is True


def test_cli_parses_ask_defaults():
    parser = build_parser()
    args = parser.parse_args(["ask"])
    assert args.command == "ask"
    assert args.question == DEFAULT_QUESTION


def test_cli_parses_login():
    parser = build_parser()
    args = parser.parse_args(["login", "--timeout", "66"])
    assert args.command == "login"
    assert args.timeout == 66


def test_cli_parses_start():
    parser = build_parser()
    args = parser.parse_args(["start", "--question", "q1", "--login-timeout", "120", "--no-auto-login"])
    assert args.command == "start"
    assert args.question == "q1"
    assert args.login_timeout == 120
    assert args.no_auto_login is True
