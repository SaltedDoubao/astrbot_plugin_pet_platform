"""插件入口：注册平台适配器，并把 AstrBot 生命周期钩子映射到桌宠状态。"""
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register

from .pet_hooks import PetHookEmitter

# noqa: F401 —— 导入即触发 @register_platform_adapter 副作用
from .pet_platform import PetPlatform  # noqa: F401


@register("astrbot_plugin_pet_platform", "dsh-pet", "dsh-pet 桌宠平台", "0.1.0")
class PetPlatformPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.emitter = PetHookEmitter()
        self._bind_platform()

    def _platform_instances(self):
        """返回当前已创建的 dsh_pet 平台实例（可能尚未创建）。"""
        instances = getattr(
            getattr(self.context, "platform_manager", None), "get_insts", None
        )
        if instances is None:
            return []
        result = []
        for instance in instances():
            meta = getattr(instance, "meta", None)
            if meta is None:
                continue
            if getattr(meta(), "id", None) == "dsh_pet":
                result.append(instance)
        return result

    def _bind_platform(self) -> None:
        for instance in self._platform_instances():
            self.emitter.bind(instance)

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        # 平台实例可能在插件加载之后才创建；就绪后再绑定一次。
        self._bind_platform()

    @filter.on_llm_request()
    async def on_llm_request(self, event, request):
        self.emitter.emit("on_llm_request", event)

    @filter.on_agent_begin()
    async def on_agent_begin(self, event, run_context=None):
        self.emitter.emit("on_agent_begin", event)

    @filter.on_using_llm_tool()
    async def on_using_llm_tool(self, event, tool=None, tool_args=None):
        # AstrBot 传入的是 FunctionTool 对象（而非工具名）。
        self.emitter.emit(
            "on_using_llm_tool", event, str(getattr(tool, "name", None) or "工具")
        )

    @filter.on_llm_tool_respond()
    async def on_llm_tool_respond(
        self, event, tool=None, tool_args=None, tool_result=None
    ):
        self.emitter.emit("on_llm_tool_respond", event)

    @filter.on_llm_response()
    async def on_llm_response(self, event, response=None):
        self.emitter.emit("on_llm_response", event)

    @filter.on_agent_done()
    async def on_agent_done(self, event, run_context=None, response=None):
        self.emitter.emit("on_agent_done", event)

    @filter.after_message_sent()
    async def after_message_sent(self, event):
        self.emitter.emit("after_message_sent", event)

    async def terminate(self):
        # 插件卸载或热重载时关闭桌宠平台，避免残留 HTTP 服务与后台任务。
        for instance in self._platform_instances():
            terminate = getattr(instance, "terminate", None)
            if terminate is not None:
                await terminate()
