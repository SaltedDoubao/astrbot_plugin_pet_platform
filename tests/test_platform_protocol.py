"""平台协议行为：主动消息声明、最终回复过滤、错误响应映射。"""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("astrbot.api.platform")

from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.metrics import Metric

from astrbot_plugin_pet_platform.pet_hooks import PetHookEmitter
from astrbot_plugin_pet_platform.pet_platform import PetPlatform


@pytest.fixture(autouse=True)
def _disable_metrics(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(Metric, "upload", _noop)


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


async def make_event(platform, request_id="r1"):
    await platform.handle_send("main", request_id, "hi")
    return platform._event_queue.get_nowait()


def test_meta_does_not_claim_proactive_support():
    meta = make_platform().meta()
    assert meta.support_proactive_message is False
    assert meta.support_streaming_message is False


async def test_send_by_session_is_defensive_noop():
    platform = make_platform()
    await platform.send_by_session(
        SimpleNamespace(session_id="main"), MessageChain().message("x")
    )
    assert platform.outbox.replay(0) == []


async def test_normal_chain_produces_exactly_one_reply():
    platform = make_platform()
    event = await make_event(platform)
    await event.send(MessageChain().message("answer"))
    records = platform.outbox.replay(0)
    assert [record["event"] for record in records] == ["reply"]
    assert records[0]["requestId"] == "r1"
    assert records[0]["text"] == "answer"


@pytest.mark.parametrize(
    "chain_type", ["tool_call", "tool_direct_result", "reasoning", "break"]
)
async def test_non_final_chains_do_not_produce_reply(chain_type):
    platform = make_platform()
    event = await make_event(platform)
    await event.send(MessageChain(type=chain_type).message("internal"))
    assert platform.outbox.replay(0) == []


async def test_tool_chain_does_not_settle_before_real_answer():
    platform = make_platform()
    event = await make_event(platform)
    await event.send(MessageChain(type="tool_call").message("calling tool"))
    assert platform.outbox.replay(0) == []
    await event.send(MessageChain().message("real answer"))
    records = platform.outbox.replay(0)
    assert len(records) == 1
    assert records[0]["text"] == "real answer"


async def test_streaming_aggregates_only_final_text():
    platform = make_platform()
    event = await make_event(platform)

    async def chunks():
        yield MessageChain(type="tool_call").message("tool status")
        yield MessageChain(type="reasoning").message("thinking")
        yield MessageChain(type="break")
        yield MessageChain().message("final ")

    await event.send_streaming(chunks())
    records = platform.outbox.replay(0)
    assert len(records) == 1
    assert records[0]["event"] == "reply"
    assert records[0]["text"] == "final "


async def test_error_response_emits_error_not_success():
    platform = make_platform()
    event = await make_event(platform)
    emitter = PetHookEmitter()
    emitter.bind(platform)
    response = SimpleNamespace(role="err", completion_text="secret-detail")

    emitter.emit("on_llm_response", event, response=response)
    records = platform.outbox.replay(0)
    assert [record["event"] for record in records] == ["status", "error", "notify"]
    assert records[0]["state"] == "error"
    assert records[1]["code"] == "llm-error"
    assert records[1]["requestId"] == "r1"
    assert records[1]["message"] == "模型调用失败"
    assert records[2]["kind"] == "error"
    assert "secret-detail" not in str(records)

    # on_agent_done 看到同一 err 响应：不重复报错，也不发 success。
    emitter.emit("on_agent_done", event, response=response)
    emitter.emit("after_message_sent", event)
    assert len(platform.outbox.replay(0)) == 3


async def test_non_error_agent_done_still_emits_success():
    platform = make_platform()
    event = await make_event(platform)
    emitter = PetHookEmitter()
    emitter.bind(platform)
    emitter.emit(
        "on_agent_done", event, response=SimpleNamespace(role="assistant")
    )
    records = platform.outbox.replay(0)
    assert [record["event"] for record in records] == ["status"]
    assert records[0]["state"] == "success"
