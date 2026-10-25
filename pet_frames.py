"""SSE 事件帧工厂与 MessageChain 文本提取。

只负责把业务值整理成固定形状；不负责发送，也不依赖 AstrBot 类型。
不变量：所有帧都带 event 与 petId（error 允许省略 petId）；task 截断到 TASK_TEXT_MAX。
"""
from __future__ import annotations

from typing import Any

TASK_TEXT_MAX = 120


def reply_event(pet_id: str, request_id: str, text: str) -> dict[str, Any]:
    return {"event": "reply", "petId": pet_id, "requestId": request_id, "text": text}


def status_event(pet_id: str, state: str, task: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"event": "status", "petId": pet_id, "state": state}
    if task:
        event["task"] = task[:TASK_TEXT_MAX]
    return event


def notify_event(pet_id: str, kind: str, text: str = "") -> dict[str, Any]:
    return {"event": "notify", "petId": pet_id, "kind": kind, "text": text}


def error_event(code: str, message: str, pet_id: str = "", request_id: str = "") -> dict[str, Any]:
    event: dict[str, Any] = {"event": "error", "code": code, "message": message}
    if pet_id:
        event["petId"] = pet_id
    if request_id:
        event["requestId"] = request_id
    return event


def chain_to_text(chain: list[Any]) -> str:
    parts: list[str] = []
    for component in chain:
        kind = type(component).__name__
        if kind == "Plain":
            parts.append(str(getattr(component, "text", "")))
        elif kind == "Image":
            parts.append("[图片]")
        elif kind == "Record":
            parts.append("[语音]")
        elif kind == "Video":
            parts.append("[视频]")
        else:
            parts.append(f"[{kind}]")
    return "".join(parts)
