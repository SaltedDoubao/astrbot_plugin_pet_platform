"""碎碎念纯函数测试：不导入 AstrBot，只用 fake context。"""
import asyncio

from astrbot_plugin_pet_platform.pet_whisper import build_whisper_prompt, whisper_prompt


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
