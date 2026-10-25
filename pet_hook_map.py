"""AstrBot 钩子名 → 桌宠档位。只做映射，不依赖 AstrBot。"""
from __future__ import annotations

_STATUS = {
    "on_llm_request": "thinking",
    "on_agent_begin": "working",
    "on_using_llm_tool": "working",
    "on_llm_tool_respond": "working",
    "on_llm_response": "result",
    "on_agent_done": "success",
    "after_message_sent": "success",
}


def hook_status(hook: str) -> str | None:
    return _STATUS.get(hook)
