"""桌宠平台的鉴权与请求校验。

只做纯判定：不读配置、不写日志、不访问网络。
不变量：令牌比较使用 hmac.compare_digest；空令牌拒绝所有请求。
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AuthConfig:
    token: str
    pet_ids: frozenset[str]


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    code: str = ""
    message: str = ""


def check_auth(headers: Mapping[str, str], config: AuthConfig) -> AuthResult:
    if not config.token:
        return AuthResult(False, "server-token-empty", "插件未配置访问令牌")
    supplied = headers.get("Authorization", "")
    expected = f"Bearer {config.token}"
    if not hmac.compare_digest(supplied, expected):
        return AuthResult(False, "unauthorized", "令牌无效")
    return AuthResult(True)


def validate_send(body: Any, config: AuthConfig) -> tuple[dict[str, str] | None, AuthResult]:
    if not isinstance(body, dict):
        return None, AuthResult(False, "bad-request", "请求体必须是 JSON 对象")
    pet_id = body.get("petId")
    request_id = body.get("requestId")
    text = body.get("text")
    if not isinstance(pet_id, str) or pet_id not in config.pet_ids:
        return None, AuthResult(False, "forbidden-pet", "petId 不在白名单")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        return None, AuthResult(False, "bad-request", "requestId 非法")
    if not isinstance(text, str) or not text.strip() or len(text) > 32768:
        return None, AuthResult(False, "bad-request", "text 为空或超长")
    return {"petId": pet_id, "requestId": request_id, "text": text}, AuthResult(True)
