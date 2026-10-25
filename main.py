"""插件入口：import 平台模块以触发注册。"""
from astrbot.api.star import Context, Star, register

# noqa: F401 —— 导入即触发 @register_platform_adapter 副作用
from pet_platform import PetPlatform  # noqa: F401


@register("astrbot_plugin_pet_platform", "dsh-pet", "dsh-pet 桌宠平台", "0.1.0")
class PetPlatformPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
