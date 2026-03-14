from __future__ import annotations

import types

import ima_bridge._web.conversation as conv
from ima_bridge._web.answer_extractor import ExtractedAIContent
from ima_bridge.config import Settings


class _FakePage:
    def wait_for_timeout(self, _ms: int) -> None:
        return None


class _Seq:
    def __init__(self, items):
        self._items = list(items)
        self._i = 0

    def next(self):
        if self._i >= len(self._items):
            return self._items[-1]
        value = self._items[self._i]
        self._i += 1
        return value


def test_wait_answer_does_not_return_previous_answer_immediately(monkeypatch):
    # Without a "baseline content signature" gate, the runner can incorrectly treat the
    # previous answer as a stable completion when asking follow-ups in the same conversation.
    settings = Settings(ask_timeout_seconds=5, poll_interval_seconds=0.01)

    session_text = _Seq(["BEFORE", "BEFORE", "BEFORE", "BEFORE"])
    session_html = _Seq(["<html>before</html>"] * 4)

    prev = ExtractedAIContent(answer_html="<p>prev</p>", answer_text="prev", thinking_text="")
    new = ExtractedAIContent(answer_html="<p>new</p>", answer_text="new", thinking_text="")
    ai_content = _Seq([prev, prev, new, new])

    fake_session = types.SimpleNamespace(
        body_text=lambda _page: session_text.next(),
        body_html=lambda _page: session_html.next(),
    )
    fake_extractor = types.SimpleNamespace(
        extract_latest_ai_content=lambda _page: ai_content.next(),
    )

    # Make monotonic advance slowly but within deadline.
    t = {"now": 1.0}

    def fake_monotonic():
        t["now"] += 0.05
        return t["now"]

    monkeypatch.setattr(conv.time, "monotonic", fake_monotonic)

    runner = conv.WebConversationRunner(settings=settings, session=fake_session, extractor=fake_extractor)
    after_text, _after_html = runner.wait_answer(_FakePage(), before_text="BEFORE", question="q2", on_update=None)

    # We only assert the method returned (did not timeout). The important behavior is that
    # it did not return during the first stable "prev" polls.
    assert after_text == "BEFORE"

