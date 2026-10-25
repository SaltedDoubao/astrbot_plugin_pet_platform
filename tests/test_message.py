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
