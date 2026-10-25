"""碎碎念生成：合并 system prompt 与用户指令，调用 AstrBot 的 llm_generate。

不构造事件、不写对话记忆；失败只回固定文案，异常细节不回给客户端。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("astrbot_plugin_pet_platform")


def build_whisper_prompt(system_prompt: str, prompt: str) -> str:
    system_prompt = (system_prompt or "").strip()
    prompt = (prompt or "").strip()
    return f"{system_prompt}\n\n{prompt}" if system_prompt else prompt


async def whisper_prompt(context, system_prompt: str, prompt: str, provider_id: str) -> dict:
    text = build_whisper_prompt(system_prompt, prompt)
    try:
        response = await context.llm_generate(
            chat_provider_id=provider_id or None,
            prompt=text,
        )
    except Exception:
        # 异常可能带地址、凭据或请求头；日志只记固定文案，响应不回细节。
        logger.error("whisper generation failed")
        return {"error": {"code": "generate-error", "message": "碎碎念生成失败"}}
    return {"text": getattr(response, "completion_text", "") or ""}
