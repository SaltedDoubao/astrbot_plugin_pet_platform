"""碎碎念纯函数测试：不导入 AstrBot，只用 fake context。"""
import asyncio

from astrbot_plugin_pet_platform.pet_whisper import (
    build_whisper_prompt,
    resolve_whisper_provider,
    whisper_prompt,
)


class FakeResponse:
    def __init__(self, text):
        self.completion_text = text


class FakeContext:
    def __init__(self, text="whisper"):
        self.text = text
        self.calls = []

    async def llm_generate(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.text)


class FakeProvider:
    def __init__(self, provider_id):
        self.provider_config = {"id": provider_id}


class FakeProviderContext:
    def __init__(self, provider, error=False):
        self.provider = provider
        self.error = error
        self.calls = 0

    async def get_using_provider_async(self):
        self.calls += 1
        if self.error:
            raise RuntimeError("secret-token-123")
        return self.provider


def test_whisper_prompt_merges_system_and_calls_provider():
    context = FakeContext()
    result = asyncio.run(whisper_prompt(context, "你是猫", "说一句", "prov-1"))
    assert result == {"text": "whisper"}
    assert context.calls == [
        {"chat_provider_id": "prov-1", "prompt": "你是猫\n\n说一句"}
    ]


def test_whisper_error_does_not_leak_exception_text():
    class BrokenContext:
        async def llm_generate(self, **kwargs):
            raise RuntimeError("secret-token-123")

    result = asyncio.run(whisper_prompt(BrokenContext(), "", "说一句", ""))
    assert result == {"error": {"code": "generate-error", "message": "碎碎念生成失败"}}
    assert "secret-token-123" not in str(result)


def test_build_whisper_prompt_without_system():
    assert build_whisper_prompt("", "说一句") == "说一句"


def test_resolve_whisper_provider_prefers_configured_id():
    context = FakeProviderContext(FakeProvider("default-prov"))
    result = asyncio.run(resolve_whisper_provider(context, " prov-1 "))
    assert result == "prov-1"
    assert context.calls == 0


def test_resolve_whisper_provider_falls_back_to_default_provider():
    context = FakeProviderContext(FakeProvider("default-prov"))
    assert asyncio.run(resolve_whisper_provider(context, "")) == "default-prov"
    assert context.calls == 1


def test_resolve_whisper_provider_returns_empty_without_provider():
    context = FakeProviderContext(None)
    assert asyncio.run(resolve_whisper_provider(context, "")) == ""


def test_resolve_whisper_provider_returns_empty_on_error():
    context = FakeProviderContext(FakeProvider("default-prov"), error=True)
    assert asyncio.run(resolve_whisper_provider(context, "")) == ""

