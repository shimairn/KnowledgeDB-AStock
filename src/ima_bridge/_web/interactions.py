from __future__ import annotations

from playwright.sync_api import Locator, Page


def click_locator_candidates(page: Page, locator: Locator, max_candidates: int = 8) -> bool:
    try:
        count = locator.count()
    except Exception:
        return False

    for index in range(min(count, max_candidates)):
        candidate = locator.nth(index)
        if click_with_fallback(page, candidate):
            return True
    return False


def click_with_fallback(page: Page, locator: Locator) -> bool:
    try:
        if not locator.is_visible():
            return False
    except Exception:
        pass

    attempts = (
        lambda: locator.click(timeout=1800),
        lambda: (locator.scroll_into_view_if_needed(timeout=1800), locator.click(timeout=1800)),
        lambda: locator.click(timeout=1800, force=True),
        lambda: locator.evaluate("(element) => element.click()"),
    )
    for attempt in attempts:
        try:
            attempt()
            return True
        except Exception:
            continue

    try:
        box = locator.bounding_box()
        if box is not None:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            return True
    except Exception:
        pass
    return False
