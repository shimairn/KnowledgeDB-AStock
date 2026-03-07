from __future__ import annotations

from ima_bridge.utils import incremental_text


def test_incremental_text_cuts_prefix():
    before = "header\nleft panel"
    after = "header\nleft panel\nquestion\nanswer"
    assert incremental_text(before, after, "question") == "answer"

