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


def _provider_id(provider) -> str:
    """从 provider 实例取配置 id；取不到时返回空串。

    AstrBot 4.29 的 Provider 由 AbstractProvider 统一挂载 provider_config，
    id 就存放在该字典里，不需要再触发 meta() 的 provider 类型查表。
    """
    if provider is None:
        return ""
    config = getattr(provider, "provider_config", None)
    if not isinstance(config, dict):
        return ""
    return str(config.get("id", "") or "").strip()


async def resolve_whisper_provider(context, configured: str) -> str:
    """确定碎碎念使用的 provider id。

    配置了就用配置值；留空则回退到 AstrBot 当前对话 provider。
    解析失败或无可用 provider 时返回空串，交调用方给出固定错误文案。
    """
    configured = (configured or "").strip()
    if configured:
        return configured
    try:
        provider = await context.get_using_provider_async()
    except Exception:
        # 只记固定文案，避免日志出现 provider 配置或凭据。
        logger.error("whisper provider resolution failed")
        return ""
    return _provider_id(provider)


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
