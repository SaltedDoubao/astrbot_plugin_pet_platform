"""HTTP 服务生命周期测试：只验证 create_app 能被 aiohttp 托管。

不导入 AstrBot，也不依赖 PetPlatform；平台层的接线由集成验证覆盖。
"""
import asyncio

import pytest
from aiohttp import ClientSession, web

from astrbot_plugin_pet_platform.pet_auth import AuthConfig
from astrbot_plugin_pet_platform.pet_outbox import Outbox
from astrbot_plugin_pet_platform.pet_server import create_app


class FakePlatform:
    """满足 PetPlatformLike 协议的最小替身。"""

    def __init__(self):
        self.outbox = Outbox()

    def sessions(self):
        return []

    async def handle_send(self, pet_id, request_id, text):
        return None

    async def handle_whisper(self, body):
        return {"text": ""}


def test_app_can_start_and_stop_on_random_port():
    async def scenario():
        config = AuthConfig(token="t", pet_ids=frozenset({"main"}))
        app = create_app(FakePlatform(), config)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        try:
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            assert port > 0
            # 端口真的可服务：带令牌请求健康检查，确认响应来自该 app。
            async with ClientSession() as session:
                async with session.get(
                    f"http://127.0.0.1:{port}/v1/health",
                    headers={"Authorization": "Bearer t"},
                ) as response:
                    assert response.status == 200
                    assert (await response.json())["platformId"] == "dsh_pet"
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


async def test_platform_run_serves_then_terminate_closes_port():
    """PetPlatform.run() 真正托管 HTTP；terminate() 后清空 runner 并释放端口。"""
    pytest.importorskip("astrbot.api.platform")

    from astrbot_plugin_pet_platform.pet_platform import PetPlatform

    platform = PetPlatform(
        {
            "token": "t",
            "pet_ids": ["main"],
            "bind_host": "127.0.0.1",
            "bind_port": 0,
        },
        {},
        asyncio.Queue(),
    )
    task = asyncio.create_task(platform.run())
    try:
        # 端口由系统分配：等 runner 报告监听地址后再发请求。
        port = 0
        for _ in range(100):
            addresses = platform._runner.addresses if platform._runner else []
            if addresses:
                port = addresses[0][1]
                break
            await asyncio.sleep(0.05)
        assert port > 0

        async with ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/v1/health",
                headers={"Authorization": "Bearer t"},
            ) as response:
                assert response.status == 200
                assert (await response.json())["platformId"] == "dsh_pet"

        await platform.terminate()
        await asyncio.wait_for(task, timeout=5)
        assert platform._runner is None
        # 服务已停止：同一端口不再接受连接。
        with pytest.raises(OSError):
            await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=2
            )
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
