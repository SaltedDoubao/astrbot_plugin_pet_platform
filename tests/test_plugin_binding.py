"""插件→平台实例的 context 注入：初始绑定与平台重建后的补绑定。"""
import pytest

pytest.importorskip("astrbot.api.platform")

from astrbot_plugin_pet_platform.main import PetPlatformPlugin


class FakeMeta:
    id = "dsh_pet"


class FakePlatformInstance:
    def __init__(self):
        self.context = None
        self._meta = FakeMeta()

    def meta(self):
        return self._meta

    def set_context(self, context):
        self.context = context


class FakePlatformManager:
    def __init__(self, instances):
        self.instances = instances

    def get_insts(self):
        return list(self.instances)


class FakeContext:
    def __init__(self, instances):
        self.platform_manager = FakePlatformManager(instances)


def test_plugin_binds_context_on_init():
    instance = FakePlatformInstance()
    context = FakeContext([instance])
    plugin = PetPlatformPlugin(context, {})
    assert instance.context is context
    assert plugin.emitter._platform is instance


async def test_plugin_rebinds_context_after_platform_reload():
    context = FakeContext([])
    plugin = PetPlatformPlugin(context, {})
    instance = FakePlatformInstance()
    context.platform_manager.instances.append(instance)

    await plugin.on_platform_loaded()

    assert instance.context is context
    assert plugin.emitter._platform is instance
