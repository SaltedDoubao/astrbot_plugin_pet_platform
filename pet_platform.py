"""dsh_pet 平台：注册、事件注入与回复回传。

平台把桌宠请求构造成 AstrBot 事件提交给管线；
事件子类重写 send()，把 LLM 回复写入发件箱供 SSE 下发。
不变量：同一 requestId 在 TTL 内只提交一次；日志不含消息正文。
"""
from __future__ import annotations

import asyncio
import logging
import time

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import (
    AstrBotMessage,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)

from .pet_frames import chain_to_text, reply_event
from .pet_message import RequestDeduper, build_message
from .pet_outbox import Outbox

logger = logging.getLogger("astrbot_plugin_pet_platform")


class PetMessageEvent(AstrMessageEvent):
    """桌宠消息事件：把 AstrBot 的回复回传到平台发件箱。"""

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        platform: "PetPlatform",
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.platform = platform

    async def send(self, message: MessageChain) -> None:
        text = chain_to_text(list(getattr(message, "chain", [])))
        self.platform.outbox.append(
            reply_event(
                self.session.session_id,
                getattr(self.message_obj, "message_id", ""),
                text,
            )
        )
        await super().send(message)


@register_platform_adapter(
    "dsh_pet",
    "dsh-pet 桌宠平台",
    default_config_tmpl={
        "type": "dsh_pet",
        "id": "dsh_pet",
        "enable": True,
        "token": "",
        "bind_host": "127.0.0.1",
        "bind_port": 6199,
        "pet_ids": ["main"],
    },
)
class PetPlatform(Platform):
    def __init__(self, platform_config, platform_settings, event_queue):
        super().__init__(platform_config, event_queue)
        self.config = platform_config
        self.settings = platform_settings
        self._stop = asyncio.Event()
        self.outbox = Outbox(
            buffer_size=int(platform_config.get("event_buffer_size", 256))
        )
        self.deduper = RequestDeduper()
        self._sessions: dict[str, float] = {}

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="dsh_pet",
            description="dsh-pet desktop pet platform",
            id="dsh_pet",
        )

    async def handle_send(self, pet_id: str, request_id: str, text: str) -> None:
        """接受桌宠请求：去重后构造事件并提交；重复请求静默忽略。"""
        if not self.deduper.first_seen(pet_id, request_id):
            return
        self._sessions[pet_id] = time.time()
        message = build_message(pet_id, request_id, text)
        event = PetMessageEvent(text, message, self.meta(), pet_id, self)
        self.commit_event(event)

    def sessions(self) -> list[dict]:
        return [
            {"petId": pet_id, "lastActiveAt": at}
            for pet_id, at in self._sessions.items()
        ]

    async def run(self):
        logger.info("dsh_pet platform started; waiting for stop")
        await self._stop.wait()

    async def send_by_session(self, session, message_chain):
        logger.info("send_by_session: %s", session)
        await super().send_by_session(session, message_chain)
