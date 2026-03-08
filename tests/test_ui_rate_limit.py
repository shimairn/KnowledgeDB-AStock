from __future__ import annotations

from ima_bridge.ui_rate_limit import UIRateLimiter


def test_ui_rate_limiter_rejects_when_window_exceeded():
    current = 100.0

    def clock() -> float:
        return current

    limiter = UIRateLimiter(per_minute=2, max_concurrent_per_ip=2, clock=clock)

    assert limiter.try_acquire("1.1.1.1").allowed is True
    limiter.release("1.1.1.1")
    assert limiter.try_acquire("1.1.1.1").allowed is True
    limiter.release("1.1.1.1")

    decision = limiter.try_acquire("1.1.1.1")

    assert decision.allowed is False
    assert decision.retry_after_seconds == 60


def test_ui_rate_limiter_enforces_per_ip_concurrency_and_allows_other_ip():
    limiter = UIRateLimiter(per_minute=10, max_concurrent_per_ip=1)

    first = limiter.try_acquire("1.1.1.1")
    second_same_ip = limiter.try_acquire("1.1.1.1")
    third_other_ip = limiter.try_acquire("2.2.2.2")

    assert first.allowed is True
    assert second_same_ip.allowed is False
    assert second_same_ip.retry_after_seconds == 1
    assert third_other_ip.allowed is True

    limiter.release("1.1.1.1")
    limiter.release("2.2.2.2")

    fourth = limiter.try_acquire("1.1.1.1")
    assert fourth.allowed is True
