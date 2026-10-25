"""AstrBot 生命周期钩子的发射器：把状态/通知写入发件箱。

不注册钩子本身（@filter 必须位于 Star 插件类）；不调用模型、不读写记忆。
不变量：只处理 UMO 前缀为 dsh_pet: 的事件；发射异常不得向上抛。
"""
from __future__ import annotations

import logging

from .pet_frames import error_event, notify_event, status_event
from .pet_hook_map import hook_status
from .pet_message import RequestDeduper

logger = logging.getLogger("astrbot_plugin_pet_platform")


class PetHookEmitter:
    def __init__(self):
        self._platform = None
        # 同一请求的 on_llm_response 与 on_agent_done 都可能看到 err；
        # 用 TTL 去重，避免重复报错，也避免之后补发 success。
        self._errored = RequestDeduper(ttl_sec=300)

    def bind(self, platform) -> None:
        self._platform = platform

    @staticmethod
    def _request_id(event) -> str:
        return str(
            getattr(getattr(event, "message_obj", None), "message_id", "") or ""
        )

    def emit(self, hook: str, event, task: str | None = None, response=None) -> None:
        if self._platform is None:
            return
        umo = str(getattr(event, "unified_msg_origin", ""))
        if not umo.startswith("dsh_pet:"):
            return
        pet_id = getattr(getattr(event, "session", None), "session_id", None)
        if not pet_id:
            return
        request_id = self._request_id(event)
        if self._errored.is_seen(pet_id, request_id):
            # 本次请求已报错：后续钩子不得再发 success，也不重复发 error。
            return
        if getattr(response, "role", None) == "err":
            self._errored.remember(pet_id, request_id)
            try:
                self._platform.outbox.append(status_event(pet_id, "error"))
                if request_id:
                    # 让桌宠用 requestId 立即结束等待，而不是等 30 秒超时。
                    self._platform.outbox.append(
                        error_event("llm-error", "模型调用失败", pet_id, request_id)
                    )
                self._platform.outbox.append(notify_event(pet_id, "error"))
            except Exception:
                logger.exception("emit pet error failed")
            return
        state = hook_status(hook)
        if state is None:
            return
        try:
            self._platform.outbox.append(status_event(pet_id, state, task))
            if hook == "after_message_sent":
                self._platform.outbox.append(notify_event(pet_id, "completed"))
        except Exception:
            # 固定日志：不输出事件内容，避免泄露用户消息；也不让异常进入 AstrBot 管线。
            logger.exception("emit pet status failed")
