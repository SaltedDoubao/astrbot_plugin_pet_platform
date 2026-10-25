"""最小验证：注册 dsh_pet 平台，确认 AstrBot 能加载并启动 run()。"""
from __future__ import annotations

import asyncio
import logging

from astrbot.api.platform import (
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)

logger = logging.getLogger("astrbot_plugin_pet_platform")


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

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="dsh_pet",
            description="dsh-pet desktop pet platform",
            id="dsh_pet",
        )

    async def run(self):
        logger.info("dsh_pet platform started; waiting for stop")
        await self._stop.wait()

    async def send_by_session(self, session, message_chain):
        logger.info("send_by_session: %s", session)
        await super().send_by_session(session, message_chain)
