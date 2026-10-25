"""pet 侧 HTTP + SSE 服务。

只负责 HTTP 边界：鉴权、请求解析、SSE 编码；业务由平台对象注入。
不变量：所有路由先鉴权；SSE 每帧带递增 id；心跳每 15 秒一次。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from aiohttp import web

from .pet_auth import AuthConfig, check_auth, validate_send
from .pet_outbox import Outbox


class PetPlatformLike(Protocol):
    """平台对象的注入契约：只用结构类型，不 import astrbot。"""

    outbox: Outbox

    def sessions(self) -> list[dict[str, Any]]: ...

    async def handle_send(self, pet_id: str, request_id: str, text: str) -> None: ...

    async def handle_whisper(self, body: dict[str, Any]) -> dict[str, Any]: ...


def create_app(platform: PetPlatformLike, config: AuthConfig) -> web.Application:
    app = web.Application()
    app["platform"] = platform
    app["auth"] = config
    app.router.add_get("/v1/health", health)
    app.router.add_get("/v1/sessions", sessions)
    app.router.add_post("/v1/send", send)
    app.router.add_post("/v1/whisper", whisper)
    app.router.add_get("/v1/events", events)
    return app


def _authorized(request: web.Request) -> bool:
    return check_auth(request.headers, request.app["auth"]).ok


def _unauthorized() -> web.Response:
    return web.json_response({"ok": False, "error": "unauthorized"}, status=401)


async def health(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    return web.json_response({"ok": True, "platformId": "dsh_pet", "version": "0.1.0"})


async def sessions(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    return web.json_response({"sessions": request.app["platform"].sessions()})


async def send(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad-request"}, status=400)
    parsed, auth = validate_send(body, request.app["auth"])
    if not auth.ok:
        # 未知 pet 是权限问题（403），请求体结构问题才是 400。
        status = 400 if auth.code == "bad-request" else 403
        return web.json_response({"ok": False, "error": auth.code}, status=status)
    await request.app["platform"].handle_send(
        parsed["petId"], parsed["requestId"], parsed["text"]
    )
    return web.json_response({"ok": True, "requestId": parsed["requestId"]}, status=202)


async def whisper(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"code": "bad-request", "message": "JSON 无效"}}, status=400
        )
    result = await request.app["platform"].handle_whisper(body)
    status = 200 if "text" in result else 502
    return web.json_response(result, status=status)


async def events(request: web.Request) -> web.StreamResponse:
    if not _authorized(request):
        return _unauthorized()
    try:
        since = int(request.query.get("since", "0") or "0")
    except ValueError:
        since = 0
    outbox: Outbox = request.app["platform"].outbox
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        }
    )
    await response.prepare(request)
    try:
        for record in outbox.replay(since):
            await _write_sse(response, record)
        queue, unsubscribe = outbox.subscribe()
        try:
            while True:
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    # 注释行只保活连接，不产生事件，也不占 id。
                    await response.write(b": ping\n\n")
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
