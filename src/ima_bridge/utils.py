from __future__ import annotations

import logging
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def longest_common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def incremental_text(before: str, after: str, question: str) -> str:
    if not after:
        return ""
    if not before:
        return after.strip()

    prefix_len = longest_common_prefix_length(before, after)
    delta = after[prefix_len:].strip()
    if not delta:
        return ""

    if question:
        pos = delta.find(question)
        if pos != -1 and pos < 16:
            delta = delta[pos + len(question) :].lstrip(" :\n\r\t")

    return delta.strip()


def extract_reference_lines(answer_text: str) -> list[str]:
    references: list[str] = []
    for line in str(answer_text or "").splitlines():
        line_text = line.strip()
        if not line_text:
            continue
        if line_text.startswith("[") and "]" in line_text:
            references.append(line_text)
    return references


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return logging.getLogger(name)
