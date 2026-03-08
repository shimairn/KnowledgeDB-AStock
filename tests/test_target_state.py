from __future__ import annotations

from ima_bridge.target_state import TargetStateStore


def test_target_state_store_remember_load_and_clear(tmp_path):
    path = tmp_path / "target.txt"
    store = TargetStateStore(path=path, base_url="https://ima.qq.com/", generic_paths={"", "/", "/wikis"})

    assert store.remember("https://ima.qq.com/wiki/123", "matched body", lambda text: "matched" in text) is True
    assert store.load() == "https://ima.qq.com/wiki/123"

    store.clear()
    assert store.load() is None


def test_target_state_store_rejects_generic_and_invalid_urls(tmp_path):
    path = tmp_path / "target.txt"
    store = TargetStateStore(path=path, base_url="https://ima.qq.com/", generic_paths={"", "/", "/wikis"})

    assert store.can_persist("https://ima.qq.com/wikis", "matched body", lambda text: True) is False
    assert store.can_persist("https://example.com/wiki/123", "matched body", lambda text: True) is False
    assert store.remember("https://ima.qq.com/wiki/123", "missed body", lambda text: "matched" in text) is False



def test_target_state_store_strips_query_and_fragment(tmp_path):
    path = tmp_path / "target.txt"
    store = TargetStateStore(path=path, base_url="https://ima.qq.com/", generic_paths={"", "/", "/wikis"})

    assert store.remember("https://ima.qq.com/wiki/123?conversation=abc#latest", "matched body", lambda text: True) is True
    assert store.load() == "https://ima.qq.com/wiki/123"
