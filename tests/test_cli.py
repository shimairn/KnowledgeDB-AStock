from __future__ import annotations

from ima_bridge.cli import DEFAULT_QUESTION, build_parser


def test_cli_parses_health():
    parser = build_parser()
    args = parser.parse_args(["--instance", "win2", "--port", "9330", "health"])
    assert args.command == "health"
    assert args.instance == "win2"
    assert args.port == 9330


def test_cli_parses_ask_defaults():
    parser = build_parser()
    args = parser.parse_args(["ask"])
    assert args.command == "ask"
    assert args.question == DEFAULT_QUESTION
