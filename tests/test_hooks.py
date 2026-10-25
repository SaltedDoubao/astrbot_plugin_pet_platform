"""生命周期钩子测试：纯映射与发射器，不导入 AstrBot。

钩子装饰器由 AstrBot 加载器覆盖，这里只验证可独立运行的部分。
"""
import pytest

from astrbot_plugin_pet_platform.pet_hook_map import hook_status
from astrbot_plugin_pet_platform.pet_hooks import PetHookEmitter
from astrbot_plugin_pet_platform.pet_outbox import Outbox


class FakeSession:
    def __init__(self, session_id):
        self.session_id = session_id


class FakeEvent:
    def __init__(self, umo="dsh_pet:FriendMessage:main", session_id="main"):
        self.unified_msg_origin = umo
        self.session = FakeSession(session_id)


class FakePlatform:
    def __init__(self):
        self.outbox = Outbox()


def frames(platform):
    """读取发件箱内容并去掉 Outbox 自带的 seq，便于断言业务帧。"""
    return [
        {key: value for key, value in record.items() if key != "seq"}
        for record in platform.outbox.replay(0)
    ]


def test_hook_status_mapping():
    assert hook_status("on_llm_request") == "thinking"
    assert hook_status("on_agent_begin") == "working"
    assert hook_status("on_using_llm_tool") == "working"
    assert hook_status("on_llm_tool_respond") == "working"
    assert hook_status("on_llm_response") == "result"
    assert hook_status("on_agent_done") == "success"
    assert hook_status("after_message_sent") == "success"
    assert hook_status("unknown") is None


def test_emit_writes_status_frame_for_pet_event():
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit("on_agent_begin", FakeEvent())

    assert frames(platform) == [
        {"event": "status", "petId": "main", "state": "working"},
    ]


def test_emit_passes_task_for_tool_hook():
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit("on_using_llm_tool", FakeEvent(), "web_search")

    assert frames(platform) == [
        {"event": "status", "petId": "main", "state": "working", "task": "web_search"},
    ]


def test_after_message_sent_emits_success_and_completed():
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit("after_message_sent", FakeEvent())

    assert frames(platform) == [
        {"event": "status", "petId": "main", "state": "success"},
        {"event": "notify", "petId": "main", "kind": "completed", "text": ""},
    ]


def test_emit_ignores_events_from_other_platforms():
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit("on_agent_begin", FakeEvent(umo="aiocqhttp:FriendMessage:main"))

    assert frames(platform) == []


def test_emit_ignores_unknown_hook():
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit("unknown", FakeEvent())

    assert frames(platform) == []


def test_emit_without_binding_is_noop():
    emitter = PetHookEmitter()

    # 未绑定平台时直接忽略，不抛异常。
    emitter.emit("on_agent_begin", FakeEvent())


def test_emit_ignores_event_without_session_id():
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit("on_agent_begin", FakeEvent(session_id=""))

    assert frames(platform) == []


def test_emit_swallows_outbox_errors(monkeypatch):
    class BrokenOutbox:
        def append(self, event):
            raise RuntimeError("secret-token-123")

    class BrokenPlatform:
        def __init__(self):
            self.outbox = BrokenOutbox()

    emitter = PetHookEmitter()
    emitter.bind(BrokenPlatform())

    # 钩子异常不得进入 AstrBot 管线。
    emitter.emit("on_agent_begin", FakeEvent())


@pytest.mark.parametrize(
    ("hook", "state"),
    [
        ("on_llm_request", "thinking"),
        ("on_agent_begin", "working"),
        ("on_using_llm_tool", "working"),
        ("on_llm_tool_respond", "working"),
        ("on_llm_response", "result"),
        ("on_agent_done", "success"),
        ("after_message_sent", "success"),
    ],
)
def test_emit_covers_every_mapped_hook(hook, state):
    platform = FakePlatform()
    emitter = PetHookEmitter()
    emitter.bind(platform)

    emitter.emit(hook, FakeEvent())

    assert frames(platform)[0] == {
        "event": "status",
        "petId": "main",
        "state": state,
    }
