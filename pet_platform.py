"""dsh_pet 平台：注册、事件注入与回复回传。

平台把桌宠请求构造成 AstrBot 事件提交给管线；
事件子类重写 send()，把 LLM 回复写入发件箱供 SSE 下发。
不变量：同一 requestId 在 TTL 内只提交一次；日志不含消息正文。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator

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
from .pet_whisper import resolve_whisper_provider, whisper_prompt

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
        self.pet_platform = platform

    async def send(self, message: MessageChain) -> None:
        text = chain_to_text(list(getattr(message, "chain", [])))
        self.pet_platform.outbox.append(
            reply_event(
                self.session.session_id,
                getattr(self.message_obj, "message_id", ""),
                text,
            )
        )
        await super().send(message)

    async def send_streaming(
        self,
        generator: AsyncGenerator[MessageChain | None, None],
        use_fallback: bool = False,
    ) -> None:
        """把流式结果整段回传。

        AstrBot 4.29 基类 send_streaming 只上传指标、不消费生成器；
        本平台不支持真实流式，必须自行聚合，否则回复会丢失。
        """
        parts: list[str] = []
        async for chain in generator:
            if chain is not None:
                parts.append(chain_to_text(list(getattr(chain, "chain", []))))
        text = "".join(parts)
        if text:
            await self.send(MessageChain().message(text))
        await super().send_streaming(generator, use_fallback)


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
            # 只回传整段回复；不声明真实流式，避免管线走平台未实现的流式路径。
            support_streaming_message=False,
            support_proactive_message=True,
        )

    async def handle_send(self, pet_id: str, request_id: str, text: str) -> None:
        """接受桌宠请求：去重后构造事件并提交；重复请求静默忽略。"""
        if not self.deduper.first_seen(pet_id, request_id):
            return
        self._sessions[pet_id] = time.time()
        message = build_message(pet_id, request_id, text)
        event = PetMessageEvent(text, message, self.meta(), pet_id, self)
        self.commit_event(event)

    async def handle_whisper(self, body: dict) -> dict:
        """生成碎碎念：只校验白名单与 prompt，绕开会话管线。"""
        pet_id = str(body.get("petId", ""))
        if pet_id not in self.config.get("pet_ids", ["main"]):
            return {"error": {"code": "forbidden-pet", "message": "petId 不在白名单"}}
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            return {"error": {"code": "bad-request", "message": "prompt 为空"}}
        provider = await resolve_whisper_provider(
            self.context, str(self.config.get("whisper_provider_id", ""))
        )
        if not provider:
            return {
                "error": {
                    "code": "generate-error",
                    "message": "未配置可用的碎碎念服务商",
                }
            }
        return await whisper_prompt(
            self.context, str(body.get("systemPrompt", "")), prompt, provider
        )

    def sessions(self) -> list[dict]:
        return [
            {"petId": pet_id, "lastActiveAt": at}
            for pet_id, at in self._sessions.items()
        ]

    async def run(self):
        logger.info("dsh_pet platform started; waiting for stop")
        await self._stop.wait()

    async def terminate(self) -> None:
        """停止平台运行循环。HTTP 服务清理由后续任务补全。"""
        self._stop.set()

    async def send_by_session(self, session, message_chain):
        logger.info("send_by_session: %s", session)
        await super().send_by_session(session, message_chain)
