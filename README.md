# ConsoleX2API

<p align="center">
  <b>将 console.x.ai 转换为 OpenAI 兼容接口的轻量网关</b>
</p>

<p align="center">
  <a href="#功能特性">功能特性</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#接口说明">接口说明</a> ·
  <a href="#管理后台">管理后台</a> ·
  <a href="#docker-compose-部署">Docker 部署</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-OpenAI%20Compatible-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/Storage-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Deploy-Docker%20Compose-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

---

## 项目简介

ConsoleX2API 是一个面向 `console.x.ai` 的 OpenAI 兼容网关。它把上游 `console.x.ai/v1/responses`、Realtime Voice 等能力包装为常见的 OpenAI 风格接口，方便接入现有客户端、脚本和代理工具。

项目目标很明确：

- 让客户端按 OpenAI API 习惯调用 Grok/console.x.ai。
- 支持多账号 SSO 池、自动轮换、失败记录和后台管理。
- 保留请求里的 `tools`、`tool_choice`、`reasoning`、`reasoning_effort` 等关键参数。
- 不把 `team_id` 写死在 `.env`，每个账号独立携带自己的 `team_id`。

> 注意：本项目当前不提供 `/v1/images/*`、`/v1/videos/*` 生成/编辑接口。图像相关能力指的是 Chat/Responses 请求中的图像输入。

## 功能特性

### OpenAI 兼容接口

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/realtime/client_secrets`
- `WS /v1/realtime?model=grok-voice-think-fast-1.0`

### 请求能力

- 支持流式和非流式输出。
- 支持 Chat Completions 的 `image_url`，会转换为 Responses `input_image`。
- 默认搜索工具对齐当前 HAR：
  - `web_search.enable_image_understanding = true`
  - `x_search.enable_video_understanding = true`
- 用户自带的 `tools`、`tool_choice` 完全原样保留，不强行改写。
- 支持 `reasoning_effort` 和 Responses `reasoning` 参数。

### 账号池

- SQLite 持久化账号。
- TXT 批量导入，格式为一行一个账号：

```txt
sso-token-1,team-id-1
sso=token-2,team-id-2
```

- 导入账号自动命名为 `1`、`2`、`3`。
- 新导入账号默认 `active`。
- 每个账号独立生成自己的 Referer：

```txt
https://console.x.ai/team/<team_id>/chat-playground
```

### 管理后台

- 独立 Admin Key 登录页。
- 左侧栏白灰简约管理界面。
- 账号导入、追加、编辑、启用、禁用、删除。
- 批量刷新账号状态，显示实时刷新结果。
- 异常账号筛选、状态/失败数/检查时间排序。
- 运行配置页面支持 API Key、Admin Key、代理、Cloudflare、模型列表等配置。
- 敏感配置只显示掩码，空密码字段不会覆盖旧值。

### Realtime Voice

- 代理 `/v1/realtime/client_secrets`。
- WebSocket 双向透传 x.ai Realtime 协议。
- 原样保留：
  - `session.update`
  - `conversation.item.create`
  - `response.create`
  - `response.cancel`
  - `input_audio_buffer.append`

## 快速开始

### 1. 安装依赖

```powershell
cd D:\Desktop\consolex
python -m pip install fastapi uvicorn curl_cffi pydantic websockets
```

### 2. 准备配置

复制示例配置：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少配置：

```env
OPENAI_API_KEY=replace-with-your-gateway-key
ADMIN_KEY=replace-with-your-admin-key
ACCOUNTS_DB=accounts.sqlite3
UPSTREAM_PROXY=http://127.0.0.1:7899
```

如果部署在海外服务器，通常不需要代理：

```env
UPSTREAM_PROXY=
```

### 3. 启动服务

必须在项目根目录启动，也就是包含 `app/` 的目录：

```powershell
cd D:\Desktop\consolex
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

或：

```powershell
python -m app
```

### 4. 打开管理后台

```txt
http://127.0.0.1:8787/admin
```

进入时输入 `ADMIN_KEY`。

## API Key 说明

项目里有两个 key，作用不同：

| 配置 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 调用 `/v1/*` 接口使用 |
| `ADMIN_KEY` | 登录 `/admin` 管理后台使用 |

请求 `/v1/models`、`/v1/chat/completions`、`/v1/responses` 时必须使用 `OPENAI_API_KEY`：

```powershell
curl http://127.0.0.1:8787/v1/models `
  -H "Authorization: Bearer replace-with-your-gateway-key"
```

如果用 `ADMIN_KEY` 调 `/v1/models`，会返回 `403 Forbidden`，这是正常行为。

## 接口说明

### 模型列表

```bash
curl http://127.0.0.1:8787/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

默认模型包含：

- `grok-4.3`
- `grok-build-0.1`
- `grok-voice-think-fast-1.0`
- `grok-4.20-0309-non-reasoning`
- `grok-4.20-0309-reasoning`
- `grok-4.20-multi-agent-0309`

也可以通过 `.env` 覆盖：

```env
GATEWAY_MODELS=grok-4.3,grok-build-0.1
```

### Chat Completions

```bash
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4.3",
    "stream": true,
    "messages": [
      {"role": "user", "content": "say pong"}
    ]
  }'
```

### 图像输入

```bash
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4.3",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "描述这张图片"},
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/png;base64,REPLACE_WITH_BASE64"
            }
          }
        ]
      }
    ]
  }'
```

### Responses

```bash
curl http://127.0.0.1:8787/v1/responses \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-build-0.1",
    "input": [
      {
        "role": "user",
        "content": [
          {"type": "input_text", "text": "介绍一下这个模型"}
        ]
      }
    ],
    "stream": true
  }'
```

### Realtime Voice

先获取 client secret：

```bash
curl http://127.0.0.1:8787/v1/realtime/client_secrets \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"expires_after":{"seconds":300}}'
```

再连接 WebSocket：

```txt
ws://127.0.0.1:8787/v1/realtime?model=grok-voice-think-fast-1.0
```

WebSocket 支持两种鉴权方式：

- Header：`Authorization: Bearer <OPENAI_API_KEY>`
- Query：`?api_key=<OPENAI_API_KEY>`

## 管理后台

后台地址：

```txt
http://127.0.0.1:8787/admin
```

后台能力：

| 模块 | 功能 |
| --- | --- |
| 账号管理 | 导入、追加、编辑、启用、禁用、删除 |
| 批量刷新 | SSE 实时显示每个账号刷新结果 |
| 状态筛选 | active、disabled、cooling、invalid、failed、异常账号 |
| 运行配置 | API Key、Admin Key、代理、Cloudflare、模型列表 |
| 安全处理 | 密钥脱敏展示，空密钥不覆盖旧值 |

TXT 导入格式：

```txt
sso-token-1,team-id-1
sso-token-2,team-id-2
```

不要只使用一个全局 `team_id`。每个账号应独立携带自己的 `team_id`。

## Docker Compose 部署

### 1. 配置环境变量

```bash
cp .env.example .env
```

### 2. 启动

```bash
docker compose up -d --build
```

Compose 默认会把账号数据库持久化到：

```txt
./data/accounts.sqlite3
```

### 3. 查看日志

```bash
docker compose logs -f
```

## 配置项

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | `/v1/*` 调用密钥 |
| `ADMIN_KEY` | 建议 | `/admin` 登录密钥 |
| `ACCOUNTS_DB` | 否 | SQLite 账号库路径 |
| `UPSTREAM_SSO` | 否 | 单账号兜底，不推荐长期使用 |
| `UPSTREAM_CF_COOKIES` | 否 | Cloudflare 相关 cookies |
| `UPSTREAM_CF_CLEARANCE` | 否 | 单独的 `cf_clearance` |
| `UPSTREAM_URL` | 否 | 默认 `https://console.x.ai/v1/responses` |
| `UPSTREAM_X_CLUSTER` | 否 | 默认 `https://us-east-1.api.x.ai` |
| `UPSTREAM_REFERER` | 否 | 只作为无 `team_id` 时的兜底 |
| `UPSTREAM_PROXY` | 否 | 本地代理，例如 `http://127.0.0.1:7899` |
| `UPSTREAM_IMPERSONATE` | 否 | `curl_cffi` 浏览器指纹 |
| `REQUEST_TIMEOUT_S` | 否 | 上游请求超时时间 |
| `GATEWAY_MODELS` | 否 | 自定义模型列表 |

运行时配置也可以由后台写入 `config.toml`。系统环境变量优先级最高。

## 常见问题

### `No module named 'app'`

你不在项目根目录启动。请进入包含 `app/` 的目录：

```powershell
cd D:\Desktop\consolex
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

### `/v1/models` 返回 `403 Forbidden`

你大概率用了 `ADMIN_KEY`。`/v1/*` 接口必须使用 `OPENAI_API_KEY`。

```powershell
curl http://127.0.0.1:8787/v1/models `
  -H "Authorization: Bearer $env:OPENAI_API_KEY"
```

### 新模型没有出现

检查 `.env`：

```env
GATEWAY_MODELS=
HAR_FILE_PATH=
```

如果 `GATEWAY_MODELS` 不为空，会覆盖默认模型列表。清空后重启服务即可使用默认模型列表。

### 管理后台能进，但 API 调不通

后台使用 `ADMIN_KEY`，API 使用 `OPENAI_API_KEY`。两者不要混用。

### 账号导入后请求失败

检查 TXT 是否是一行一个账号：

```txt
sso,teamid
```

不要把所有账号都绑定到同一个全局 `UPSTREAM_REFERER`。

## 开发与测试

运行测试：

```bash
python -m unittest discover -s tests
```

语法检查：

```bash
python -m py_compile app/accounts.py app/admin/routes.py app/upstream/xai_client.py app/openai/routes.py app/main.py
```

## 安全建议

- 不要提交 `.env`、账号库、cookies、HAR 文件。
- `OPENAI_API_KEY` 和 `ADMIN_KEY` 建议使用不同值。
- 生产环境建议只开放必要端口，并使用反向代理加 TLS。
- `UPSTREAM_CF_CLEARANCE`、SSO、账号数据库都属于敏感数据。

## 许可证

请根据你的实际发布策略补充许可证信息。
