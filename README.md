# ConsoleX2API

<p align="center">
  <b>将 console.x.ai 封装为 OpenAI 兼容接口的轻量级网关</b>
</p>

<p align="center">
  <a href="#功能概览">功能概览</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#管理后台">管理后台</a> ·
  <a href="#接口说明">接口说明</a> ·
  <a href="#docker-compose-部署">Docker 部署</a> ·
  <a href="#常见问题">常见问题</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-OpenAI%20Compatible-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/Storage-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white">
  <img alt="Realtime-Voice" src="https://img.shields.io/badge/Realtime-Voice-111827?style=flat-square">
  <img alt="Docker" src="https://img.shields.io/badge/Deploy-Docker%20Compose-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

---

## 项目简介

ConsoleX2API 是一个面向 `console.x.ai` 的 OpenAI 兼容网关。它将上游 `console.x.ai/v1/responses`、Realtime Voice 等能力包装为常见的 OpenAI 风格接口，让现有客户端、脚本、代理工具可以按熟悉的方式接入。

它重点解决四件事：

- 使用 OpenAI API 习惯调用 console.x.ai。
- 使用 SQLite 管理多账号 SSO 池，每个账号独立保存 `team_id`。
- 提供独立 Admin Key 管理后台，支持账号、配置、批量刷新和状态筛选。
- 保留请求中的 `tools`、`tool_choice`、`reasoning`、`reasoning_effort` 等关键参数。

> 本项目当前不提供 `/v1/images/*`、`/v1/videos/*` 生成或编辑接口。图像相关能力指 Chat/Responses 请求中的图像输入。

## 功能概览

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| OpenAI Models | 已支持 | `GET /v1/models` |
| Chat Completions | 已支持 | `POST /v1/chat/completions`，支持流式和非流式 |
| Responses | 已支持 | `POST /v1/responses` |
| 图像输入 | 已支持 | Chat `image_url` 自动转换为 Responses `input_image` |
| Tools 透传 | 已支持 | 用户自带 `tools`、`tool_choice` 不被强行改写 |
| Thinking 参数 | 已支持 | 保留 `reasoning`、`reasoning_effort` |
| Realtime Voice | 已支持 | client secret + WebSocket 双向透传 |
| SQLite 账号池 | 已支持 | 多 SSO、多 team、多状态管理 |
| 管理后台 | 已支持 | 独立登录页、白灰左侧栏、配置和账号管理 |
| Docker Compose | 已支持 | 数据库持久化到 `./data/accounts.sqlite3` |

## 工作方式

```txt
OpenAI Client
    |
    |  /v1/models
    |  /v1/chat/completions
    |  /v1/responses
    |  /v1/realtime
    v
ConsoleX2API Gateway
    |
    |  账号选择、请求转换、SSE 包装、错误包装
    |  tools / reasoning 参数保留
    v
console.x.ai upstream
```

账号池不依赖全局固定 team。每个账号导入时都带自己的 `team_id`，网关会按账号生成对应 Referer：

```txt
https://console.x.ai/team/<team_id>/chat-playground
```

## 快速开始

### 1. 安装依赖

```powershell
cd D:\Desktop\consolex
python -m pip install fastapi uvicorn curl_cffi pydantic websockets
```

### 2. 准备配置

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少设置：

```env
OPENAI_API_KEY=replace-with-your-gateway-key
ADMIN_KEY=replace-with-your-admin-key
ACCOUNTS_DB=accounts.sqlite3
UPSTREAM_PROXY=http://127.0.0.1:7899
```

如果部署在海外服务器，通常可以关闭代理：

```env
UPSTREAM_PROXY=
```

不要在 `.env` 中写死某一个账号的 team。账号的 `team_id` 应该通过管理后台或 TXT 导入进入 SQLite。

### 3. 启动服务

必须在项目根目录启动，也就是包含 `app/` 的目录：

```powershell
cd D:\Desktop\consolex
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

也可以使用模块入口：

```powershell
python -m app
```

### 4. 打开后台

```txt
http://127.0.0.1:8787/admin
```

进入后台时输入 `.env` 中的 `ADMIN_KEY`。

## 账号导入

TXT 格式是一行一个账号：

```txt
sso-token-1,team-id-1
sso-token-2,team-id-2
sso=token-3,team-id-3
```

导入规则：

- TXT 不需要 name 字段。
- 账号名自动按顺序生成：`1`、`2`、`3`。
- 新导入账号默认状态为 `active`。
- 每个账号必须使用自己的 `team_id`。
- 不要把所有账号绑定到同一个全局 `UPSTREAM_REFERER`。

## 管理后台

后台地址：

```txt
http://127.0.0.1:8787/admin
```

后台使用独立 Admin Key 登录，不与 `/v1/*` API Key 混用。

| 模块 | 功能 |
| --- | --- |
| 登录页 | 进入后台前输入 `ADMIN_KEY` |
| 账号管理 | 导入、追加、编辑、启用、禁用、删除 |
| 批量刷新 | SSE 实时显示每个账号刷新结果 |
| 状态筛选 | active、disabled、cooling、invalid、failed、异常账号 |
| 排序查看 | 按状态、失败次数、检查时间等字段查看 |
| 运行配置 | API Key、Admin Key、代理、Cloudflare、模型列表 |
| 安全展示 | 密钥脱敏显示，空密钥不会覆盖旧值 |

## 接口说明

### 鉴权

项目里有两个 key：

| 配置 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 调用 `/v1/*` 接口 |
| `ADMIN_KEY` | 登录 `/admin` 管理后台 |

请求 `/v1/models`、`/v1/chat/completions`、`/v1/responses` 时必须使用 `OPENAI_API_KEY`：

```powershell
curl http://127.0.0.1:8787/v1/models `
  -H "Authorization: Bearer replace-with-your-gateway-key"
```

使用 `ADMIN_KEY` 调用 `/v1/models` 会返回 `403 Forbidden`，这是正常行为。

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

获取 client secret：

```bash
curl http://127.0.0.1:8787/v1/realtime/client_secrets \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"expires_after":{"seconds":300}}'
```

连接 WebSocket：

```txt
ws://127.0.0.1:8787/v1/realtime?model=grok-voice-think-fast-1.0
```

WebSocket 支持两种鉴权方式：

- Header：`Authorization: Bearer <OPENAI_API_KEY>`
- Query：`?api_key=<OPENAI_API_KEY>`

网关会双向透传 Realtime 帧，包括：

- `session.update`
- `conversation.item.create`
- `response.create`
- `response.cancel`
- `input_audio_buffer.append`

## Docker Compose 部署

### 1. 准备配置

```bash
cp .env.example .env
```

根据部署环境修改 `.env`：

```env
OPENAI_API_KEY=replace-with-your-gateway-key
ADMIN_KEY=replace-with-your-admin-key
UPSTREAM_PROXY=
```

### 2. 启动服务

```bash
docker compose up -d --build
```

### 3. 查看日志

```bash
docker compose logs -f
```

Compose 默认将账号数据库持久化到：

```txt
./data/accounts.sqlite3
```

## 配置项

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | `/v1/*` 调用密钥 |
| `ADMIN_KEY` | 建议 | `/admin` 登录密钥 |
| `ACCOUNTS_DB` | 否 | SQLite 账号库路径 |
| `UPSTREAM_SSO` | 否 | 单账号兜底，不推荐长期使用 |
| `UPSTREAM_COOKIE` | 否 | 上游 Cookie 兜底 |
| `UPSTREAM_CF_COOKIES` | 否 | Cloudflare 相关 cookies |
| `UPSTREAM_CF_CLEARANCE` | 否 | 单独的 `cf_clearance` |
| `UPSTREAM_URL` | 否 | 默认 `https://console.x.ai/v1/responses` |
| `UPSTREAM_X_CLUSTER` | 否 | 默认 `https://us-east-1.api.x.ai` |
| `UPSTREAM_ORIGIN` | 否 | 默认 `https://console.x.ai` |
| `UPSTREAM_REFERER` | 否 | 只作为无 `team_id` 时的兜底 |
| `UPSTREAM_USER_AGENT` | 否 | 上游请求 User-Agent |
| `UPSTREAM_PROXY` | 否 | 本地代理，例如 `http://127.0.0.1:7899` |
| `UPSTREAM_IMPERSONATE` | 否 | `curl_cffi` 浏览器指纹 |
| `UPSTREAM_SKIP_SSL_VERIFY` | 否 | 是否跳过 SSL 验证 |
| `REQUEST_TIMEOUT_S` | 否 | 上游请求超时时间 |
| `GATEWAY_MODELS` | 否 | 自定义模型列表 |
| `HAR_FILE_PATH` | 否 | 可选 HAR 模型解析来源 |

运行时配置也可以由后台写入 `config.toml`。系统环境变量优先级最高。

## 常见问题

### `No module named 'app'`

启动目录不对。请进入包含 `app/` 的项目根目录：

```powershell
cd D:\Desktop\consolex
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

### `/v1/models` 返回 `403 Forbidden`

通常是把 `ADMIN_KEY` 当成 API Key 使用了。`/v1/*` 接口必须使用 `OPENAI_API_KEY`。

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

如果 `GATEWAY_MODELS` 不为空，它会覆盖默认模型列表。清空后重启服务即可使用默认模型列表。

### 管理后台能进，但 API 调不通

后台使用 `ADMIN_KEY`，API 使用 `OPENAI_API_KEY`。两者不要混用。

### 账号导入后请求失败

先确认 TXT 是否是一行一个账号：

```txt
sso,teamid
```

再确认账号不是共用同一个 team，并且没有把 `team_id` 写死到全局 `UPSTREAM_REFERER`。

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
- 如果部署到公网，建议在反向代理层增加访问控制和请求日志。

## 免责声明

本项目仅用于个人学习、接口适配和自有账号管理。使用时请遵守目标服务的条款、账号规则和所在地区法律法规。
