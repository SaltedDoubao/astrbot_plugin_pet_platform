"""SSE 发件箱：环形缓冲、续传与订阅队列。

只负责事件排队与重放；不负责 HTTP 编码，也不决定事件内容。
不变量：seq 单调递增；缓冲满时丢最旧；订阅队列满时丢最旧并补一条 resync。
"""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Callable


class Outbox:
    def __init__(self, buffer_size: int = 256, subscriber_queue_size: int = 64):
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max(1, buffer_size))
        self._subscriber_queue_size = max(2, subscriber_queue_size)
        self._seq = 0
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def append(self, event: dict[str, Any]) -> int:
        self._seq += 1
        record = {**event, "seq": self._seq}
        self._buffer.append(record)
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(
                    {
                        "event": "resync",
                        "petId": record.get("petId", ""),
                        "reason": "overflow",
                        "seq": self._seq,
                    }
                )
                continue
            queue.put_nowait(record)
        return self._seq

    def replay(self, since: int) -> list[dict[str, Any]]:
        return [record for record in self._buffer if record["seq"] > since]

    def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], Callable[[], None]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._subscriber_queue_size)
        self._subscribers.add(queue)

        def unsubscribe() -> None:
            self._subscribers.discard(queue)

        return queue, unsubscribe

    def close(self) -> None:
        self._subscribers.clear()
