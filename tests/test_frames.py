from dataclasses import dataclass

from astrbot_plugin_pet_platform.pet_frames import (
    TASK_TEXT_MAX,
    chain_to_text,
    error_event,
    notify_event,
    reply_event,
    status_event,
)


@dataclass
class Plain:
    text: str


@dataclass
class Image:
    file: str = "x.png"


def test_reply_and_status_frames():
    assert reply_event("main", "r1", "hi") == {
        "event": "reply",
        "petId": "main",
        "requestId": "r1",
        "text": "hi",
    }
    assert status_event("main", "working", "x" * 200)["task"] == "x" * TASK_TEXT_MAX


def test_notify_and_error_frames():
    assert notify_event("main", "completed") == {
        "event": "notify",
        "petId": "main",
        "kind": "completed",
        "text": "",
    }
    assert error_event("timeout", "slow", "main", "r1") == {
        "event": "error",
        "code": "timeout",
        "message": "slow",
        "petId": "main",
        "requestId": "r1",
    }


def test_chain_to_text_handles_text_and_media():
    assert chain_to_text([Plain("你好"), Image()]) == "你好[图片]"
