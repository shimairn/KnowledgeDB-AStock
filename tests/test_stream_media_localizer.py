import types

from ima_bridge.config import Settings
import ima_bridge.web_worker_service as wws
from ima_bridge.ui_media import LocalizedMedia


def test_stream_localizer_throttles_and_uses_cache(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_download_images_to_local(*, answer_html: str, url_prefix: str, **_kwargs):
        calls.append("download")
        # Simulate localizing a blob URL.
        localized = answer_html.replace("blob:img-1", f"{url_prefix}/h.png")
        return localized, [
            LocalizedMedia(original_src="blob:img-1", local_relpath="h.png", content_type="image/png")
        ]

    t = {"now": 1.0}

    def fake_monotonic():
        return t["now"]

    monkeypatch.setattr(wws, "download_images_to_local", fake_download_images_to_local)
    monkeypatch.setattr(wws.time, "monotonic", fake_monotonic)

    settings = Settings(artifacts_dir=tmp_path, instance="inst")
    src_cache: dict[str, str] = {}
    placeholder_cache: dict[str, str] = {}
    localizer = wws.StreamAnswerHtmlLocalizer(
        settings=settings,
        web_driver=types.SimpleNamespace(),
        page=object(),
        context=object(),
        output_dir=tmp_path / "ui-media",
        url_prefix="/api/media/inst",
        max_images=4,
        interval_ms=800,
        src_cache=src_cache,
        placeholder_cache=placeholder_cache,
    )

    html = '<div><p>hello</p><img src="blob:img-1" /></div>'
    out1 = localizer.localize_stream(html)
    assert "/api/media/inst/h.png" in out1
    assert calls == ["download"]

    # Within throttle window: should not download again.
    t["now"] = 1.2
    out2 = localizer.localize_stream(html)
    assert "/api/media/inst/h.png" in out2
    assert calls == ["download"]

    # After throttle window: should still avoid downloading because cache can rewrite to local.
    t["now"] = 2.2
    out3 = localizer.localize_stream(html)
    assert "/api/media/inst/h.png" in out3
    assert calls == ["download"]


def test_stream_localizer_injects_vector_placeholders(tmp_path, monkeypatch):
    def fake_download_images_to_local(*, answer_html: str, **_kwargs):
        return answer_html, []

    def fake_snapshot_vector_media(*, placeholders: list[str], **_kwargs):
        assert placeholders == ["vector-0"]
        return {"vector-0": "/api/media/inst/vector-0.png"}

    t = {"now": 10.0}

    def fake_monotonic():
        return t["now"]

    monkeypatch.setattr(wws, "download_images_to_local", fake_download_images_to_local)
    monkeypatch.setattr(wws, "_snapshot_vector_media", fake_snapshot_vector_media)
    monkeypatch.setattr(wws.time, "monotonic", fake_monotonic)

    settings = Settings(artifacts_dir=tmp_path, instance="inst", web_vector_snapshot_max=6)
    localizer = wws.StreamAnswerHtmlLocalizer(
        settings=settings,
        web_driver=types.SimpleNamespace(),
        page=object(),
        context=object(),
        output_dir=tmp_path / "ui-media",
        url_prefix="/api/media/inst",
        max_images=0,
        interval_ms=800,
        src_cache={},
        placeholder_cache={},
    )

    html = '<div class="_markdown_x"><p>chart</p><img data-ima-bridge-media="vector-0" /></div>'
    out = localizer.localize_stream(html)
    assert 'src="/api/media/inst/vector-0.png"' in out

