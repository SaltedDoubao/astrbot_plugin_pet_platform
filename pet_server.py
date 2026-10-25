"""pet 侧 HTTP + SSE 服务。

只负责 HTTP 边界：鉴权、请求解析、SSE 编码；业务由平台对象注入。
不变量：所有路由先鉴权；SSE 每帧带递增 id；心跳每 15 秒一次；
buffer-gap / overflow 的 resync 使用哨兵 id 0，不参与递增。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from aiohttp import web

from .pet_auth import AuthConfig, AuthResult, check_auth, validate_send
from .pet_outbox import Outbox


class PetPlatformLike(Protocol):
    """平台对象的注入契约：只用结构类型，不 import astrbot。"""

    outbox: Outbox

    def sessions(self) -> list[dict[str, Any]]: ...

    async def handle_send(self, pet_id: str, request_id: str, text: str) -> None: ...

    async def handle_whisper(self, body: dict[str, Any]) -> dict[str, Any]: ...


# 类型化 AppKey：避免字符串键拼写错误，也消除 aiohttp 的 NotAppKeyWarning。
PLATFORM_KEY: web.AppKey[PetPlatformLike] = web.AppKey("platform", PetPlatformLike)
AUTH_KEY: web.AppKey[AuthConfig] = web.AppKey("auth", AuthConfig)


def create_app(platform: PetPlatformLike, config: AuthConfig) -> web.Application:
    app = web.Application()
    app[PLATFORM_KEY] = platform
    app[AUTH_KEY] = config
    app.router.add_get("/v1/health", health)
    app.router.add_get("/v1/sessions", sessions)
    app.router.add_post("/v1/send", send)
    app.router.add_post("/v1/whisper", whisper)
    app.router.add_get("/v1/events", events)
    return app


def _auth(request: web.Request) -> AuthResult:
    return check_auth(request.headers, request.app[AUTH_KEY])


def _unauthorized(auth: AuthResult) -> web.Response:
    # 保持 spec §9.1 的形状，并保留具体 code（如 server-token-empty）。
    return web.json_response({"error": {"code": auth.code or "unauthorized"}}, status=401)


async def health(request: web.Request) -> web.Response:
    auth = _auth(request)
    if not auth.ok:
        return _unauthorized(auth)
    return web.json_response({"ok": True, "platformId": "dsh_pet", "version": "0.1.0"})


async def sessions(request: web.Request) -> web.Response:
    auth = _auth(request)
    if not auth.ok:
        return _unauthorized(auth)
    return web.json_response({"sessions": request.app[PLATFORM_KEY].sessions()})


async def send(request: web.Request) -> web.Response:
    auth = _auth(request)
    if not auth.ok:
        return _unauthorized(auth)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad-request"}, status=400)
    parsed, auth = validate_send(body, request.app[AUTH_KEY])
    if not auth.ok:
        # 未知 pet 是权限问题（403），请求体结构问题才是 400。
        status = 400 if auth.code == "bad-request" else 403
        return web.json_response({"ok": False, "error": auth.code}, status=status)
    await request.app[PLATFORM_KEY].handle_send(
        parsed["petId"], parsed["requestId"], parsed["text"]
    )
    return web.json_response({"ok": True, "requestId": parsed["requestId"]}, status=202)


async def whisper(request: web.Request) -> web.Response:
    auth = _auth(request)
    if not auth.ok:
        return _unauthorized(auth)
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"code": "bad-request", "message": "JSON 无效"}}, status=400
        )
    # 非对象请求体（[]、"x"）在进入平台层前就拒绝，避免业务层误判字段。
    if not isinstance(body, dict):
        return web.json_response(
            {"error": {"code": "bad-request", "message": "请求体必须是 JSON 对象"}},
            status=400,
        )
    result = await request.app[PLATFORM_KEY].handle_whisper(body)
    if not isinstance(result, dict):
        return web.json_response(
            {"error": {"code": "bad-response", "message": "平台返回非对象"}}, status=502
        )
    if "text" in result:
        return web.json_response(result, status=200)
    error = result.get("error")
    code = error.get("code") if isinstance(error, dict) else ""
    # 未知 pet 是权限问题，请求体问题 400，其余生成失败一律 502。
    status = 403 if code == "forbidden-pet" else 400 if code == "bad-request" else 502
    return web.json_response(result, status=status)


async def events(request: web.Request) -> web.StreamResponse:
    auth = _auth(request)
    if not auth.ok:
        return _unauthorized(auth)
    try:
        since = int(request.query.get("since", "0") or "0")
    except ValueError:
        since = 0
    outbox: Outbox = request.app[PLATFORM_KEY].outbox
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        }
    )
    await response.prepare(request)
    try:
        # 先订阅再回放：回放期间到达的事件会进入队列，不会漏发；
        # 同时在回放快照内与队列里的记录靠 last_replayed_seq 去重。
        queue, unsubscribe = outbox.subscribe()
        try:
            replayed = outbox.replay(since)
            last_replayed_seq = max(
                (
                    int(record.get("seq", 0))
                    for record in replayed
                    if record.get("event") != "resync"
                ),
                default=0,
            )
            for record in replayed:
                await _write_sse(response, record)
            while True:
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    # 注释行只保活连接，不产生事件，也不占 id。
                    await response.write(b": ping\n\n")
                    continue
                # resync 是重建指令，永远投递；其余记录跳过回放阶段的重复项。
                if record.get("event") != "resync" and int(
                    record.get("seq", 0)
                ) <= last_replayed_seq:
                    continue
                await _write_sse(response, record)
        finally:
            unsubscribe()
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    return response


async def _write_sse(response: web.StreamResponse, record: dict[str, Any]) -> None:
    seq = int(record.get("seq", 0))
    event = str(record.get("event", "message"))
    payload = {key: value for key, value in record.items() if key != "seq"}
    data = json.dumps(payload, ensure_ascii=False)
    await response.write(f"id: {seq}\nevent: {event}\ndata: {data}\n\n".encode("utf-8"))
