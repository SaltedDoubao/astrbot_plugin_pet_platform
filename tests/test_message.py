"""请求去重、消息构造与回复回传的测试。

去重是纯逻辑，始终执行；消息构造与 send() 回传依赖 AstrBot，未安装时跳过。
"""
import asyncio

import pytest

from astrbot_plugin_pet_platform.pet_message import RequestDeduper


def test_deduper_rejects_same_pet_and_request_id():
    d = RequestDeduper(ttl_sec=300, now=lambda: 1000)
    assert d.first_seen("main", "r1") is True
    assert d.first_seen("main", "r1") is False
    assert d.first_seen("main", "r2") is True
    assert d.first_seen("other", "r1") is True


def test_deduper_expires_after_ttl():
    now = [1000]
    d = RequestDeduper(ttl_sec=10, now=lambda: now[0])
    assert d.first_seen("main", "r1") is True
    now[0] = 1011
    assert d.first_seen("main", "r1") is True


def test_deduper_is_seen_does_not_record():
    """is_seen 只查询；remember 才落记录，供“提交成功后再登记”使用。"""
    d = RequestDeduper(ttl_sec=300, now=lambda: 1000)
    assert d.is_seen("main", "r1") is False
    d.remember("main", "r1")
    assert d.is_seen("main", "r1") is True
    # 已记录的请求不会再被 first_seen 当成首次。
    assert d.first_seen("main", "r1") is False


def test_deduper_remember_expires_after_ttl():
    now = [1000]
    d = RequestDeduper(ttl_sec=10, now=lambda: now[0])
    d.remember("main", "r1")
    assert d.is_seen("main", "r1") is True
    now[0] = 1011
    assert d.is_seen("main", "r1") is False
    # 过期后可以再次被当作首次请求处理。
    assert d.first_seen("main", "r1") is True


async def test_message_send_pushes_reply_event(monkeypatch):
    """send() 必须把回复写入平台发件箱，而不只是上传指标。"""
    pytest.importorskip("astrbot.api.event")
    monkeypatch.setenv("ASTRBOT_DISABLE_METRICS", "1")

    from astrbot.api.event import MessageChain
    from astrbot.api.message_components import Plain
    from astrbot.api.platform import PlatformMetadata

    from astrbot_plugin_pet_platform.pet_message import build_message
    from astrbot_plugin_pet_platform.pet_outbox import Outbox
    from astrbot_plugin_pet_platform.pet_platform import PetMessageEvent

    class FakePlatform:
        def __init__(self):
            self.outbox = Outbox()

    platform = FakePlatform()
    message = build_message("main", "r1", "你好")
    assert message.session_id == "main"
    assert message.message_id == "r1"
    assert message.message_str == "你好"

    event = PetMessageEvent(
        "你好",
        message,
        PlatformMetadata(name="dsh_pet", description="test", id="dsh_pet"),
        "main",
        platform,
    )
    await event.send(MessageChain([Plain(text="回复")]))
    # 让基类 send() 里 create_task 的指标任务跑完，避免悬空任务。
    await asyncio.sleep(0)

    replies = [e for e in platform.outbox.replay(0) if e.get("event") == "reply"]
    assert replies == [
        {"event": "reply", "petId": "main", "requestId": "r1", "text": "回复", "seq": 1}
    ]


async def test_empty_reply_does_not_append_event(monkeypatch):
    """空回复只走上报指标，不应在发件箱留下空 reply 事件。"""
    pytest.importorskip("astrbot.api.event")
    monkeypatch.setenv("ASTRBOT_DISABLE_METRICS", "1")

    from astrbot.api.event import MessageChain
    from astrbot.api.platform import PlatformMetadata

    from astrbot_plugin_pet_platform.pet_message import build_message
    from astrbot_plugin_pet_platform.pet_outbox import Outbox
    from astrbot_plugin_pet_platform.pet_platform import PetMessageEvent

    class FakePlatform:
        def __init__(self):
            self.outbox = Outbox()

    platform = FakePlatform()
    event = PetMessageEvent(
        "你好",
        build_message("main", "r1", "你好"),
        PlatformMetadata(name="dsh_pet", description="test", id="dsh_pet"),
        "main",
        platform,
    )

    await event.send(MessageChain([]))
    await asyncio.sleep(0)

    replies = [e for e in platform.outbox.replay(0) if e.get("event") == "reply"]
    assert replies == []


async def test_streaming_send_pushes_single_reply(monkeypatch):
    """流式结果必须聚合成恰好一条回复，不能因为基类不消费生成器而丢失。"""
    pytest.importorskip("astrbot.api.event")
    monkeypatch.setenv("ASTRBOT_DISABLE_METRICS", "1")

    from astrbot.api.event import MessageChain
    from astrbot.api.message_components import Plain
    from astrbot.api.platform import PlatformMetadata

    from astrbot_plugin_pet_platform.pet_message import build_message
    from astrbot_plugin_pet_platform.pet_outbox import Outbox
    from astrbot_plugin_pet_platform.pet_platform import PetMessageEvent

    class FakePlatform:
        def __init__(self):
            self.outbox = Outbox()

    platform = FakePlatform()
    event = PetMessageEvent(
        "你好",
        build_message("main", "r1", "你好"),
        PlatformMetadata(name="dsh_pet", description="test", id="dsh_pet"),
        "main",
        platform,
    )

    async def chunks():
        yield MessageChain([Plain(text="你")])
        yield None
        yield MessageChain([Plain(text="好呀")])

    await event.send_streaming(chunks())
    await asyncio.sleep(0)

    replies = [e for e in platform.outbox.replay(0) if e.get("event") == "reply"]
    assert replies == [
        {"event": "reply", "petId": "main", "requestId": "r1", "text": "你好呀", "seq": 1}
    ]


async def test_streaming_skips_reasoning_chains(monkeypatch):
    """推理链属于内部过程，不能混进回传给桌宠的正文。"""
    pytest.importorskip("astrbot.api.event")
    monkeypatch.setenv("ASTRBOT_DISABLE_METRICS", "1")

    from astrbot.api.event import MessageChain
    from astrbot.api.message_components import Plain
    from astrbot.api.platform import PlatformMetadata

    from astrbot_plugin_pet_platform.pet_message import build_message
    from astrbot_plugin_pet_platform.pet_outbox import Outbox
    from astrbot_plugin_pet_platform.pet_platform import PetMessageEvent

    class FakePlatform:
        def __init__(self):
            self.outbox = Outbox()

    platform = FakePlatform()
    event = PetMessageEvent(
        "你好",
        build_message("main", "r1", "你好"),
        PlatformMetadata(name="dsh_pet", description="test", id="dsh_pet"),
        "main",
        platform,
    )

    async def chunks():
        yield MessageChain([Plain(text="内部思考")], type="reasoning")
        yield None
        yield MessageChain([Plain(text="回答")])

    await event.send_streaming(chunks())
    await asyncio.sleep(0)

    replies = [e for e in platform.outbox.replay(0) if e.get("event") == "reply"]
    assert replies == [
        {"event": "reply", "petId": "main", "requestId": "r1", "text": "回答", "seq": 1}
    ]
