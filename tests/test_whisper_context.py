"""碎碎念 context 接线：缺失 context 回结构化 502，不抛 AttributeError。"""
import asyncio

import pytest

pytest.importorskip("astrbot.api.platform")

from astrbot_plugin_pet_platform.pet_platform import PetPlatform


class FakeResponse:
    def __init__(self, text):
        self.completion_text = text


class FakeProvider:
    provider_config = {"id": "fake-prov"}


class FakeContext:
    def __init__(self):
        self.calls = []

    async def get_using_provider_async(self, umo=None):
        return FakeProvider()

    async def llm_generate(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse("<reply>")


def make_platform():
    return PetPlatform(
        {
            "token": "t",
            "pet_ids": ["main"],
            "bind_host": "127.0.0.1",
            "bind_port": 0,
        },
        {},
        asyncio.Queue(),
    )


async def test_whisper_without_context_returns_structured_error():
    platform = make_platform()
    result = await platform.handle_whisper({"petId": "main", "prompt": "说一句"})
    assert result == {
        "error": {"code": "generate-error", "message": "碎碎念服务未就绪"}
    }


async def test_whisper_after_set_context_uses_provider():
    platform = make_platform()
    context = FakeContext()
    platform.set_context(context)
    result = await platform.handle_whisper(
        {"petId": "main", "systemPrompt": "你是猫", "prompt": "说一句"}
    )
    assert result == {"text": "<reply>"}
    assert platform.context is context
    assert context.calls == [
        {"chat_provider_id": "fake-prov", "prompt": "你是猫\n\n说一句"}
    ]


def test_default_config_tmpl_exposes_buffer_and_whisper_provider():
    from astrbot.core.platform.register import platform_registry

    meta = next(pm for pm in platform_registry if pm.name == "dsh_pet")
    template = meta.default_config_tmpl or {}
    assert template["event_buffer_size"] == 256
    assert template["whisper_provider_id"] == ""
