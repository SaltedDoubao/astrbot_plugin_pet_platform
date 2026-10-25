"""请求去重与 AstrBot 消息构造。

去重是纯逻辑；消息构造依赖 AstrBot，只在真实运行/集成测试里导入。
不变量：同一 (petId, requestId) 在 TTL 内只第一次返回 True。
"""
from __future__ import annotations

import time
from typing import Any, Callable


class RequestDeduper:
    """按 (petId, requestId) 做 TTL 去重，纯内存、无副作用。"""

    def __init__(self, ttl_sec: int = 300, now: Callable[[], float] = time.monotonic):
        self._ttl = ttl_sec
        self._now = now
        self._seen: dict[tuple[str, str], float] = {}

    def _purge(self, now: float) -> None:
        expired = [key for key, at in self._seen.items() if now - at > self._ttl]
        for key in expired:
            self._seen.pop(key, None)

    def is_seen(self, pet_id: str, request_id: str) -> bool:
        """只查询 TTL 内是否已记录，不写入；过期记录先清理。"""
        now = self._now()
        self._purge(now)
        return (pet_id, request_id) in self._seen

    def remember(self, pet_id: str, request_id: str) -> None:
        """登记一次已处理请求；调用方应在事件提交成功后再调用。"""
        now = self._now()
        self._purge(now)
        self._seen[(pet_id, request_id)] = now

    def first_seen(self, pet_id: str, request_id: str) -> bool:
        """首次见到返回 True；TTL 内重复返回 False；过期记录先清理。"""
        now = self._now()
        self._purge(now)
        key = (pet_id, request_id)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True


def build_message(pet_id: str, request_id: str, text: str) -> Any:
    """构造 AstrBotMessage；调用方必须已安装 AstrBot。

    message_id 直接复用 requestId，回复事件靠它做关联。
    """
    from astrbot.api.message_components import Plain
    from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType

    message = AstrBotMessage()
    message.type = MessageType.FRIEND_MESSAGE
    message.self_id = "dsh_pet"
    message.session_id = pet_id
    message.message_id = request_id
    message.sender = MessageMember(user_id=pet_id, nickname=pet_id)
    message.message = [Plain(text=text)]
    message.message_str = text
    message.raw_message = {"petId": pet_id, "requestId": request_id}
    return message
