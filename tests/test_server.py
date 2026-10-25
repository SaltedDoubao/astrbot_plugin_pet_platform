import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_pet_platform.pet_auth import AuthConfig
from astrbot_plugin_pet_platform.pet_outbox import Outbox
from astrbot_plugin_pet_platform.pet_server import create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CONFIG = AuthConfig(token=TOKEN, pet_ids=frozenset({"main"}))


class FakePlatform:
    def __init__(self):
        self.outbox = Outbox(buffer_size=8)
        self.sent = []
        self.whispered = []

    def sessions(self):
        return [{"petId": "main", "lastActiveAt": 1}]

    async def handle_send(self, pet_id, request_id, text):
        self.sent.append((pet_id, request_id, text))
        self.outbox.append(
            {"event": "reply", "petId": pet_id, "requestId": request_id, "text": "ok"}
        )

    async def handle_whisper(self, body):
        self.whispered.append(body)
        return {"text": "whisper"}


@pytest.fixture
async def client():
    platform = FakePlatform()
    app = create_app(platform, CONFIG)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client, platform
    await client.close()


async def test_health_requires_token(client):
    http, _ = client
    assert (await http.get("/v1/health")).status == 401
    response = await http.get("/v1/health", headers=AUTH)
    assert response.status == 200
    assert (await response.json())["platformId"] == "dsh_pet"


async def test_sessions_lists_platform_sessions(client):
    http, _ = client
    assert (await http.get("/v1/sessions")).status == 401
    response = await http.get("/v1/sessions", headers=AUTH)
    assert response.status == 200
    assert (await response.json()) == {"sessions": [{"petId": "main", "lastActiveAt": 1}]}


async def test_send_returns_202_and_writes_outbox(client):
    http, platform = client
    response = await http.post(
        "/v1/send",
        headers=AUTH,
        json={"petId": "main", "requestId": "r1", "text": "你好"},
    )
    assert response.status == 202
    assert platform.sent == [("main", "r1", "你好")]
    assert platform.outbox.replay(0)[0]["event"] == "reply"


async def test_send_rejects_unknown_pet(client):
    http, platform = client
    response = await http.post(
        "/v1/send",
        headers=AUTH,
        json={"petId": "other", "requestId": "r1", "text": "你好"},
    )
    assert response.status == 403
    assert (await response.json())["error"] == "forbidden-pet"
    assert platform.sent == []


async def test_send_rejects_invalid_body_with_400(client):
    http, platform = client
    for body in (
        {"petId": "main", "requestId": "r1"},
        {"petId": "main", "requestId": "", "text": "你好"},
        {"petId": "main", "requestId": "r1", "text": "   "},
    ):
        response = await http.post("/v1/send", headers=AUTH, json=body)
        assert response.status == 400
        assert (await response.json())["error"] == "bad-request"
    broken = await http.post(
        "/v1/send",
        headers={"Content-Type": "application/json", **AUTH},
        data="{",
    )
    assert broken.status == 400
    assert platform.sent == []


async def test_send_requires_token(client):
    http, platform = client
    response = await http.post(
        "/v1/send",
        json={"petId": "main", "requestId": "r1", "text": "你好"},
    )
    assert response.status == 401
    assert platform.sent == []


async def test_whisper_returns_text(client):
    http, platform = client
    response = await http.post(
        "/v1/whisper",
        headers=AUTH,
        json={"petId": "main", "requestId": "r1", "prompt": "hi"},
    )
    assert response.status == 200
    assert (await response.json()) == {"text": "whisper"}
    assert platform.whispered[0]["prompt"] == "hi"


async def test_whisper_returns_502_on_platform_error(client):
    http, platform = client

    async def failing_whisper(body):
        return {"error": {"code": "timeout", "message": "no reply"}}

    platform.handle_whisper = failing_whisper
    response = await http.post("/v1/whisper", headers=AUTH, json={"petId": "main", "prompt": "hi"})
    assert response.status == 502
    assert (await response.json())["error"]["code"] == "timeout"


async def test_events_replays_and_streams(client):
    http, platform = client
    platform.outbox.append({"event": "status", "petId": "main", "state": "working"})
    response = await http.get("/v1/events?since=0", headers=AUTH)
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    chunk = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=1)
    assert b"event: status" in chunk
    assert b"id: 1" in chunk
    response.close()


async def test_events_requires_token(client):
    http, _ = client
    assert (await http.get("/v1/events?since=0")).status == 401


class ReplayRaceOutbox(Outbox):
    """模拟回放期间并发 append。

    第一条在快照前 append：既出现在回放结果里，也进入订阅队列，必须去重。
    第二条在快照后 append：只进入订阅队列，必须补发。
    """

    def replay(self, since):
        self.append({"event": "status", "petId": "main", "state": "overlap"})
        records = super().replay(since)
        self.append({"event": "status", "petId": "main", "state": "during"})
        return records


def _sse_frame_id(chunk: bytes) -> str:
    for line in chunk.decode("utf-8").splitlines():
        if line.startswith("id: "):
            return line[len("id: ") :]
    raise AssertionError(f"帧缺少 id 行: {chunk!r}")


def _sse_frame_state(chunk: bytes) -> str:
    for line in chunk.decode("utf-8").splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])["state"]
    raise AssertionError(f"帧缺少 data 行: {chunk!r}")


async def test_events_delivers_events_arriving_during_replay_exactly_once():
    platform = FakePlatform()
    platform.outbox = ReplayRaceOutbox(buffer_size=8)
    platform.outbox.append({"event": "status", "petId": "main", "state": "seed"})
    app = create_app(platform, CONFIG)
    async with TestClient(TestServer(app)) as http:
        response = await http.get("/v1/events?since=0", headers=AUTH)
        assert response.status == 200
        frames = []
        for _ in range(3):
            chunk = await asyncio.wait_for(
                response.content.readuntil(b"\n\n"), timeout=1
            )
            frames.append((_sse_frame_id(chunk), _sse_frame_state(chunk)))
        # 回放的 seed 不被重复；快照内的 overlap 只出现一次；快照后的 during 被补发。
        assert frames == [("1", "seed"), ("2", "overlap"), ("3", "during")]
        response.close()
