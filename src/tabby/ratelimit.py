"""Tiny in-memory sliding-window rate limiter, keyed by client IP. Single process only."""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            retry = int(60 - (now - hits[0])) + 1
            raise HTTPException(429, "Too many requests, try again shortly.", headers={"Retry-After": str(retry)})
        hits.append(now)
        if len(self._hits) > 10_000:  # drop idle keys so memory stays bounded
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                del self._hits[k]

    def __call__(self, request: Request) -> None:
        self.check(request.client.host if request.client else "unknown")
