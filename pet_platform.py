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

from aiohttp import web
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import (
    AstrBotMessage,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)

from .pet_auth import AuthConfig
from .pet_frames import chain_to_text, reply_event
from .pet_message import RequestDeduper, build_message
from .pet_outbox import Outbox
from .pet_ratelimit import RateLimiter
from .pet_server import create_app
from .pet_whisper import resolve_whisper_provider, whisper_prompt

logger = logging.getLogger("astrbot_plugin_pet_platform")

# 工具调用、工具直出、推理链与流式分段都不是最终回复；
# 若把它们的文本当 reply 回传，桌宠会提前按 requestId 结束请求并丢掉真正答案。
_NON_REPLY_CHAIN_TYPES = frozenset(
    {"tool_call", "tool_direct_result", "reasoning", "break"}
)


def _is_reply_chain(message) -> bool:
    return getattr(message, "type", None) not in _NON_REPLY_CHAIN_TYPES


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
        if not _is_reply_chain(message):
            return
        text = chain_to_text(list(getattr(message, "chain", [])))
        # 空回复（例如仅上报指标）不写发件箱，避免桌宠收到空文本。
        if text:
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
            # 推理/工具状态/分段链都不是正文；空链也不参与聚合。
            if chain is None or not _is_reply_chain(chain):
                continue
            parts.append(chain_to_text(list(getattr(chain, "chain", []))))
        text = "".join(parts)
        if text:
            await self.send(MessageChain().message(text))
        await super().send_streaming(generator, use_fallback)


@register_platform_adapter(
    "dsh_pet",
    "dsh-pet 桌宠平台",
    # 注册元数据与 meta() 保持一致：不做真实流式。
    support_streaming_message=False,
    default_config_tmpl={
        "type": "dsh_pet",
        "id": "dsh_pet",
        "enable": True,
        "token": "",
        "bind_host": "127.0.0.1",
        "bind_port": 6199,
        "pet_ids": ["main"],
        "event_buffer_size": 256,
        "whisper_provider_id": "",
    },
)
class PetPlatform(Platform):
    def __init__(self, platform_config, platform_settings, event_queue):
        super().__init__(platform_config, event_queue)
        self.config = platform_config
        self.settings = platform_settings
        # 插件上下文由 Star 插件注入；缺失时碎碎念必须回结构化错误，而不是抛异常。
        self.context = None
        self._stop = asyncio.Event()
        self._runner: web.AppRunner | None = None
        self.outbox = Outbox(
            buffer_size=int(platform_config.get("event_buffer_size", 256))
        )
        # spec §11.4：默认 30 次/60 秒，按 petId 计。
        self.rate_limiter = RateLimiter(limit=30, window_sec=60)
        self.deduper = RequestDeduper()
        self._sessions: dict[str, float] = {}

    def set_context(self, context) -> None:
        """注入 Star 插件持有的 AstrBot Context，供碎碎念调用 provider。"""
        self.context = context

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="dsh_pet",
            description="dsh-pet desktop pet platform",
            id="dsh_pet",
            # 只回传整段回复；不声明真实流式，避免管线走平台未实现的流式路径。
            support_streaming_message=False,
            # v1 不实现主动消息；send_by_session 仅为防御性 no-op。
            support_proactive_message=False,
        )

    async def handle_send(self, pet_id: str, request_id: str, text: str) -> None:
        """接受桌宠请求：去重后构造事件并提交；重复请求静默忽略。

        先去重查询、提交成功后再登记，避免提交失败把请求永久标记为已处理。
        本方法全程无 await，查询与提交之间不会被并发请求插入。
        """
        if self.deduper.is_seen(pet_id, request_id):
            return
        self._sessions[pet_id] = time.time()
        message = build_message(pet_id, request_id, text)
        event = PetMessageEvent(text, message, self.meta(), pet_id, self)
        self.commit_event(event)
        self.deduper.remember(pet_id, request_id)

    async def handle_whisper(self, body: dict) -> dict:
        """生成碎碎念：只校验白名单与 prompt，绕开会话管线。"""
        pet_id = str(body.get("petId", ""))
        if pet_id not in self.config.get("pet_ids", ["main"]):
            return {"error": {"code": "forbidden-pet", "message": "petId 不在白名单"}}
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            return {"error": {"code": "bad-request", "message": "prompt 为空"}}
        if self.context is None:
            # 插件尚未完成 context 注入（或热重载竞态）：回 502，不把 AttributeError 抛成 500。
            return {
                "error": {
                    "code": "generate-error",
                    "message": "碎碎念服务未就绪",
                }
            }
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

    async def run(self) -> None:
        """启动 HTTP 服务并阻塞到 terminate()；退出时必定清理 runner。"""
        config = AuthConfig(
            token=str(self.config.get("token", "")),
            pet_ids=frozenset(self.config.get("pet_ids", ["main"])),
        )
        runner = web.AppRunner(create_app(self, config, self.rate_limiter))
        self._runner = runner
        try:
            await runner.setup()
            site = web.TCPSite(
                runner,
                str(self.config.get("bind_host", "127.0.0.1")),
                int(self.config.get("bind_port", 6199)),
            )
            await site.start()
            # site.name 只含监听地址，不含令牌或消息内容。
            logger.info("dsh_pet listening on %s", site.name)
            await self._stop.wait()
        finally:
            await runner.cleanup()
            self._runner = None

    async def terminate(self) -> None:
        """请求停止运行循环；HTTP 服务由 run() 的 finally 负责清理。"""
        self._stop.set()

    async def send_by_session(self, session, message_chain):
        # v1 不声明主动消息（meta.support_proactive_message=False）。
        # 这里只记固定文案，绝不向调用方宣称已送达，也不写发件箱。
        logger.info("dsh_pet proactive send is unsupported in v1")
