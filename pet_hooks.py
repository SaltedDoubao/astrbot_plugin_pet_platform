"""AstrBot 生命周期钩子的发射器：把状态/通知写入发件箱。

不注册钩子本身（@filter 必须位于 Star 插件类）；不调用模型、不读写记忆。
不变量：只处理 UMO 前缀为 dsh_pet: 的事件；发射异常不得向上抛。
"""
from __future__ import annotations

import logging

from .pet_frames import notify_event, status_event
from .pet_hook_map import hook_status

logger = logging.getLogger("astrbot_plugin_pet_platform")


class PetHookEmitter:
    def __init__(self):
        self._platform = None

    def bind(self, platform) -> None:
        self._platform = platform

    def emit(self, hook: str, event, task: str | None = None) -> None:
        if self._platform is None:
            return
        state = hook_status(hook)
        umo = str(getattr(event, "unified_msg_origin", ""))
        if state is None or not umo.startswith("dsh_pet:"):
            return
        pet_id = getattr(getattr(event, "session", None), "session_id", None)
        if not pet_id:
            return
        try:
            self._platform.outbox.append(status_event(pet_id, state, task))
            if hook == "after_message_sent":
                self._platform.outbox.append(notify_event(pet_id, "completed"))
        except Exception:
            # 固定日志：不输出事件内容，避免泄露用户消息；也不让异常进入 AstrBot 管线。
            logger.exception("emit pet status failed")
