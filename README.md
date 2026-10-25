# astrbot_plugin_pet_platform

把 dsh-pet 桌宠接入 AstrBot 的独立平台插件。插件在加载时注册平台适配器 `dsh_pet`，AstrBot 侧通过 HTTP + SSE 接收桌宠消息、回传模型回复与工作状态；桌宠侧只需要一个访问令牌和 `petId`。

- 平台 ID / 适配器名：`dsh_pet`
- 最低 AstrBot 版本：`4.29.0b2`（见 `metadata.yaml`，要求 `>=4.29.0b2,<5`）
- 运行依赖：`aiohttp>=3.9`（见 `requirements.txt`）

## 安装

1. 把本目录复制到 AstrBot 的 `data/plugins/astrbot_plugin_pet_platform/`。
2. 在 AstrBot 使用的 Python 环境中安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

3. 重启 AstrBot（或在 WebUI 中重载插件），让 `dsh_pet` 适配器完成注册。
4. 打开 AstrBot WebUI 的「平台」页，启用（或新增）`dsh_pet` 平台。
5. 填写 `token`、`bind_host`、`bind_port`、`pet_ids`。
6. 保存平台配置并重启 AstrBot。

> 插件重载只会重新注册适配器，不会重启已经在运行的平台实例。修改配置后请保存一次平台配置或重启 AstrBot，否则旧实例可能继续占用端口。

## 配置

### 平台配置（WebUI「平台」页，`dsh_pet`）

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | bool | `true` | 是否启用该平台实例 |
| `token` | string | 空 | 桌宠访问令牌；留空时所有请求返回 401（fail closed） |
| `bind_host` | string | `127.0.0.1` | HTTP 监听地址；默认只监听本机 |
| `bind_port` | int | `6199` | HTTP 监听端口 |
| `pet_ids` | list | `["main"]` | 允许的 `petId` 白名单；不在名单内返回 403 |
| `event_buffer_size` | int | `256` | SSE 环形缓冲大小 |
| `whisper_provider_id` | string | 空 | 碎碎念使用的 provider；留空回退当前会话 provider |

### 插件配置 schema（`_conf_schema.json`）

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | 启用 dsh_pet 平台 |
| `bind_host` | string | `127.0.0.1` | HTTP 监听地址 |
| `bind_port` | int | `6199` | HTTP 监听端口 |
| `token` | string | 空（`secret: true`） | 桌宠访问令牌；留空拒绝所有请求 |
| `pet_ids` | list | `["main"]` | 允许的 `petId` 白名单 |
| `event_buffer_size` | int | `256` | SSE 环形缓冲大小 |
| `whisper_provider_id` | string | 空 | 碎碎念使用的 provider；留空回退当前会话 provider |

注意：HTTP 服务实际读取的是「平台」页保存的 `platform_config`；`_conf_schema.json` 是插件级设置 schema，两边字段含义一致。`event_buffer_size` 与 `whisper_provider_id` 已包含在平台的 `default_config_tmpl` 中，可直接在「平台」页配置。

> `token` 只是桌宠与本插件之间的桥接令牌，**不是** AstrBot OpenAPI、Dashboard 或 WebUI 的登录凭据，也不要与它们复用同一个值。

## 最小验收

以下命令中的 `<token>` 替换为平台配置里的 `token`，`<host>` 替换为 `bind_host`（本机为 `127.0.0.1`）。所有端点都要求请求头 `Authorization: Bearer <token>`。

### 健康检查

```bash
curl -H "Authorization: Bearer <token>" http://<host>:6199/v1/health
```

预期：HTTP 200

```json
{"ok": true, "platformId": "dsh_pet", "version": "0.1.0"}
```

无令牌或令牌错误时返回 HTTP 401：`{"error": {"code": "unauthorized"}}`；令牌未配置时返回 401 且 `code` 为 `server-token-empty`。

### 订阅事件

```bash
curl -N -H "Authorization: Bearer <token>" "http://<host>:6199/v1/events?since=0"
```

预期：HTTP 200，`Content-Type: text/event-stream`。每帧格式：

```text
id: 1
event: status
data: {"event":"status","petId":"main","state":"thinking"}
```

- `id` 是单调递增的序号，重连时把它作为 `since` 参数续传。
- 空闲时每 15 秒收到一行注释心跳 `: ping`，它不是事件。
- 收到 `event: resync`（`id: 0`）表示续传出现缺口或缓冲溢出，应重新拉取全量状态，不要把它当成普通事件或续传点位。

### 发送消息

```bash
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"petId":"main","requestId":"r1","text":"你好"}' \
  http://<host>:6199/v1/send
```

预期：HTTP 202

```json
{"ok": true, "requestId": "r1"}
```

- `petId` 必须在白名单内，否则 403；`requestId` 非空且不超过 128 字符；`text` 非空且不超过 32768 字符，否则 400。
- 同一 `(petId, requestId)` 在 5 分钟 TTL 内重复提交只处理一次，重试仍返回 202，但不会重复触发对话。

### 碎碎念

```bash
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"petId":"main","requestId":"w1","systemPrompt":"你是猫","prompt":"说一句碎碎念"}' \
  http://<host>:6199/v1/whisper
```

预期：HTTP 200

```json
{"text": "..."}
```

- 碎碎念直接调用 `context.llm_generate()`，不构造 AstrBot 事件、不进入对话管线，因此 **不会把 prompt 写入对话记忆（会话历史）**。
- `petId` 不在白名单返回 403；`prompt` 为空返回 400；provider 不可用或生成失败返回 502。
- 插件会在插件加载、AstrBot 就绪以及每次平台加载完成时把 AstrBot `Context` 注入平台实例。若注入尚未完成（如平台实例刚创建或热重载竞态），本端点返回 502 `{"error":{"code":"generate-error","message":"碎碎念服务未就绪"}}`，而不是 500；通常稍后重试即可。

## 一次对话的事件序列

桌宠发送 `/v1/send` 后，SSE 通常依次出现（具体次数取决于是否发生工具调用）：

```text
status thinking        # on_llm_request
status working         # on_agent_begin；工具调用期间会再次出现，带 task 字段
status result          # on_llm_response
status success         # on_agent_done
reply                  # 模型回复：{"event":"reply","petId":"main","requestId":"r1","text":"..."}
status success         # after_message_sent
notify completed       # after_message_sent：{"event":"notify","kind":"completed"}
```

说明：AstrBot 的 respond 阶段先调用 `event.send()` 回传回复，随后才触发 `after_message_sent`，所以 `reply` 通常出现在最后一条 `success`/`notify` 之前；`success` 出现两次是正常现象。若没有可用 LLM provider，`/v1/send` 仍会返回 202，但不会产生 `reply`。

## 安全建议

- 默认只绑定 `127.0.0.1`，不要直接暴露到公网。
- 需要远程访问时，把 `bind_host` 改为 `0.0.0.0` 之前，先在前面加反向代理并启用 TLS（HTTPS/WSS），同时用防火墙限制来源 IP。
- 令牌等同于该平台的完整操作权限：持有者可发送消息、消耗模型额度。请使用足够长的随机值，并只在桌宠侧保存。
- 令牌、消息正文不会写入插件日志；错误帧只包含固定错误码和文案。

## 当前验收状态

2026-10-25 在本地 AstrBot 4.29.0-beta.2 环境用真实 `PetPlatform` + 真实 aiohttp 服务完成了 `/v1/health`、`/v1/events`、`/v1/send`、`/v1/sessions`、去重与 `terminate()` 的进程内验收；`/v1/whisper` 已验证：无 context 时返回结构化 502，注入 context + 模拟 provider 后返回 200。未接入真实 LLM provider，`reply` 帧由测试脚本手工调用 `event.send()` 注入。完整 WebUI 安装、真实模型对话与真实碎碎念仍待有 provider 的 AstrBot 实例补验。
