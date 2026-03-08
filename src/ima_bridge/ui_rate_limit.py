from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int | None = None


@dataclass
class _IPState:
    timestamps: deque[float] = field(default_factory=deque)
    inflight: int = 0


class UIRateLimiter:
    def __init__(
        self,
        per_minute: int,
        max_concurrent_per_ip: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.per_minute = max(1, per_minute)
        self.max_concurrent_per_ip = max(1, max_concurrent_per_ip)
        self._clock = clock or time.monotonic
        self._lock = Lock()
        self._states: dict[str, _IPState] = {}

    def try_acquire(self, ip: str) -> RateLimitDecision:
        current = self._clock()
        with self._lock:
            state = self._states.setdefault(ip, _IPState())
            self._prune(state, current)

            if len(state.timestamps) >= self.per_minute:
                retry_after = max(1, math.ceil(WINDOW_SECONDS - (current - state.timestamps[0])))
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

            if state.inflight >= self.max_concurrent_per_ip:
                return RateLimitDecision(allowed=False, retry_after_seconds=1)

            state.timestamps.append(current)
            state.inflight += 1
            return RateLimitDecision(allowed=True)

    def release(self, ip: str) -> None:
        current = self._clock()
        with self._lock:
            state = self._states.get(ip)
            if state is None:
                return

            if state.inflight > 0:
                state.inflight -= 1

            self._prune(state, current)
            if state.inflight == 0 and not state.timestamps:
                self._states.pop(ip, None)

    def _prune(self, state: _IPState, current: float) -> None:
        while state.timestamps and current - state.timestamps[0] >= WINDOW_SECONDS:
            state.timestamps.popleft()
