"""内存滑动窗口限流：按 key 限制单位时间内的请求数。

只做判定，不读配置、不写日志；key 由调用方决定（本插件用 petId）。
不变量：窗口内最多放行 limit 次；过期的命中记录在判定时清理。
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int = 30,
        window_sec: float = 60.0,
        now: Callable[[], float] = time.monotonic,
    ):
        self._limit = max(1, int(limit))
        self._window = max(0.0, float(window_sec))
        self._now = now
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """记一次请求；未超限返回 True，超限返回 False（不记录本次）。"""
        current = self._now()
        hits = self._hits.setdefault(str(key), deque())
        cutoff = current - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(current)
        return True
