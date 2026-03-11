from __future__ import annotations

import base64
import hashlib
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

from ima_bridge.utils import get_logger


logger = get_logger("ima_bridge.ui_media")

_DATA_IMAGE_RE = re.compile(r"^data:(image/[\w.+-]+);base64,(.+)$", re.IGNORECASE | re.DOTALL)
_IMG_SRC_LIKE_ATTRS = ("src", "data-src", "data-original", "data-url")


@dataclass(frozen=True, slots=True)
class LocalizedMedia:
    original_src: str
    local_relpath: str
    content_type: str


def _ext_from_content_type(content_type: str) -> str:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/svg+xml": "svg",
    }.get(value, "bin")


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _extract_img_srcs(html_fragment: str) -> list[str]:
    source = str(html_fragment or "").strip()
    if not source:
        return []

    class _Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.items: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._handle(tag, attrs)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._handle(tag, attrs)

        def _handle(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if (tag or "").lower() != "img":
                return
            attr_map = {str(k or "").lower(): (v or "") for k, v in attrs}
            for key in _IMG_SRC_LIKE_ATTRS:
                raw = str(attr_map.get(key, "") or "").strip()
                if raw:
                    self.items.append(html.unescape(raw))
                    return

    parser = _Collector()
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        return []

    out = parser.items
    seen: set[str] = set()
    uniq: list[str] = []
    for src in out:
        if src in seen:
            continue
        seen.add(src)
        uniq.append(src)
    return uniq


def _decode_data_image(src: str) -> tuple[bytes, str] | None:
    match = _DATA_IMAGE_RE.match(src.strip())
    if not match:
        return None
    content_type = match.group(1).lower()
    payload = match.group(2)
    try:
        return base64.b64decode(payload, validate=False), content_type
    except Exception:
        return None


def _fetch_blob_bytes(page: Page, src: str) -> tuple[bytes, str] | None:
    try:
        result = page.evaluate(
            """
            async (url) => {
              const resp = await fetch(url);
              const buf = await resp.arrayBuffer();
              const bytes = new Uint8Array(buf);
              let binary = "";
              const chunk = 0x8000;
              for (let i = 0; i < bytes.length; i += chunk) {
                binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
              }
              const b64 = btoa(binary);
              const ct = resp.headers.get("content-type") || "";
              return { b64, ct };
            }
            """,
            src,
        )
        b64 = str((result or {}).get("b64") or "")
        if not b64:
            return None
        content_type = str((result or {}).get("ct") or "").strip() or "application/octet-stream"
        return base64.b64decode(b64), content_type
    except Exception:
        return None


def _sniff_content_type(body: bytes) -> str:
    if not body:
        return "application/octet-stream"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"GIF87a") or body.startswith(b"GIF89a"):
        return "image/gif"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    head = body[:256].lstrip()
    if head.startswith(b"<svg") or head.startswith(b"<?xml") or b"<svg" in head.lower():
        return "image/svg+xml"
    return "application/octet-stream"


def _fetch_http_bytes(context: BrowserContext, src: str) -> tuple[bytes, str] | None:
    try:
        resp = context.request.get(src, timeout=25_000)
        if not resp.ok:
            return None
        body = resp.body()
        content_type = resp.headers.get("content-type", "") if hasattr(resp, "headers") else ""
        sniffed = _sniff_content_type(body) if not content_type or content_type == "application/octet-stream" else ""
        return body, (content_type or sniffed or "application/octet-stream")
    except Exception:
        return None


class _ImgSrcRewriter(HTMLParser):
    def __init__(self, src_map: dict[str, str], placeholder_map: dict[str, str] | None = None) -> None:
        super().__init__(convert_charrefs=False)
        self._src_map = src_map
        self._placeholder_map = placeholder_map or {}
        self._out: list[str] = []

    def output(self) -> str:
        return "".join(self._out)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._write_tag(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._write_tag(tag, attrs, closed=True)

    def handle_endtag(self, tag: str) -> None:
        self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._out.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._out.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._out.append(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        self._out.append(f"<![{data}]>")

    def _write_tag(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> None:
        lower = tag.lower()
        cleaned: list[tuple[str, str | None]] = []
        src_value: str | None = None
        has_alt = False
        deferred_src: str | None = None
        placeholder_id: str | None = None
        for key, value in attrs:
            if not key:
                continue
            key_lower = key.lower()
            if key_lower.startswith("on") or key_lower == "style":
                continue
            if lower == "img" and key_lower in {"class", "id", "title", "aria-label"}:
                # These can trigger server-side "decorative image" filters in the cleaner.
                continue
            if lower == "img" and key_lower in {"srcset", "width", "height"}:
                continue
            if lower == "img" and key_lower == "src":
                src_value = html.unescape(value or "")
                continue
            if lower == "img" and key_lower in {"data-src", "data-original", "data-url"}:
                deferred_src = html.unescape(value or "")
                continue
            if lower == "img" and key_lower == "data-ima-bridge-media":
                placeholder_id = html.unescape(value or "").strip() or None
                cleaned.append((key, value))
                continue
            if lower == "img" and key_lower == "alt":
                # Normalize to empty; we're primarily rendering charts/screenshots.
                cleaned.append(("alt", ""))
                has_alt = True
                continue
            cleaned.append((key, value))

        if lower == "img":
            if not src_value and deferred_src:
                src_value = deferred_src
            placeholder_src = self._placeholder_map.get(placeholder_id or "")
            if placeholder_src:
                cleaned.append(("src", placeholder_src))
            else:
                rewritten = self._src_map.get((src_value or "").strip())
                if rewritten:
                    cleaned.append(("src", rewritten))
                elif src_value is not None:
                    cleaned.append(("src", src_value))
            if not has_alt:
                cleaned.append(("alt", ""))

        parts = [f"<{tag}"]
        for key, value in cleaned:
            if value is None:
                parts.append(f" {key}")
            else:
                parts.append(f' {key}="{html.escape(str(value), quote=True)}"')
        parts.append(" />" if closed else ">")
        self._out.append("".join(parts))


def download_images_to_local(
    *,
    page: Page,
    context: BrowserContext,
    answer_html: str,
    output_dir: Path,
    url_prefix: str,
    max_images: int = 12,
    max_bytes: int = 12 * 1024 * 1024,
) -> tuple[str, list[LocalizedMedia]]:
    source = str(answer_html or "").strip()
    if not source:
        return "", []

    img_srcs = _extract_img_srcs(source)
    if not img_srcs:
        return source, []

    output_dir.mkdir(parents=True, exist_ok=True)
    src_map: dict[str, str] = {}
    localized: list[LocalizedMedia] = []

    for src in img_srcs[: max(0, int(max_images))]:
        raw = src.strip()
        if not raw or raw in src_map:
            continue
        if raw.startswith("/api/") or raw.startswith("/assets/"):
            # Already local to the UI server.
            continue

        payload: tuple[bytes, str] | None = None
        decoded = _decode_data_image(raw)
        if decoded is not None:
            payload = decoded
        elif raw.lower().startswith("blob:"):
            payload = _fetch_blob_bytes(page, raw)
        elif raw.lower().startswith(("http://", "https://")):
            payload = _fetch_http_bytes(context, raw)
        else:
            try:
                resolved = page.evaluate("url => new URL(url, location.href).href", raw)
                if isinstance(resolved, str) and resolved.lower().startswith(("http://", "https://")):
                    payload = _fetch_http_bytes(context, resolved)
            except Exception:
                payload = None

        if payload is None:
            continue

        body, content_type = payload
        if not body:
            continue
        if not content_type or content_type == "application/octet-stream":
            content_type = _sniff_content_type(body)
        if len(body) > max(0, int(max_bytes)):
            logger.info("skip image: too large bytes=%s src=%s", len(body), raw[:200])
            continue

        ext = _ext_from_content_type(content_type)
        filename = f"{_safe_hash(raw)}.{ext}"
        path = output_dir / filename
        try:
            if not path.exists():
                path.write_bytes(body)
        except Exception:
            continue

        local_url = f"{url_prefix.rstrip('/')}/{filename}"
        src_map[raw] = local_url
        localized.append(LocalizedMedia(original_src=raw, local_relpath=filename, content_type=content_type))

    if not src_map:
        return source, []

    rewriter = _ImgSrcRewriter(src_map)
    try:
        rewriter.feed(source)
        rewriter.close()
        rewritten = rewriter.output().strip()
    except Exception:
        rewritten = source

    return rewritten, localized


def inject_placeholder_img_sources(answer_html: str, placeholder_map: dict[str, str]) -> str:
    """Rewrite <img data-ima-bridge-media="..."> to point at local sources."""
    source = str(answer_html or "").strip()
    if not source or not placeholder_map:
        return source
    rewriter = _ImgSrcRewriter({}, placeholder_map=placeholder_map)
    try:
        rewriter.feed(source)
        rewriter.close()
        return rewriter.output().strip()
    except Exception:
        return source
