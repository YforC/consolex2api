# ConsoleX OpenAI Gateway

This gateway exposes OpenAI-compatible endpoints and forwards requests to `https://console.x.ai/v1/responses` using `curl_cffi` browser impersonation for Cloudflare-sensitive traffic.

## Endpoints

- `GET /v1/models`
- `POST /v1/chat/completions` (supports `stream=true`)
- `POST /v1/responses` (supports `stream=true`)
- `POST /v1/realtime/client_secrets`
- `WS /v1/realtime?model=grok-voice-think-fast-1.0`
- `GET /health`

## Environment Variables

- `OPENAI_API_KEY` (required): gateway API key for OpenAI-compatible `Authorization: Bearer <key>`
- `ADMIN_KEY` (recommended): admin UI/API key for `/admin`; falls back to `OPENAI_API_KEY` only when unset
- `ACCOUNTS_DB` (optional): SQLite account database path, default `accounts.sqlite3`
- `ACCOUNTS_FILE` (legacy optional): JSON account list path; only used when `ACCOUNTS_DB` is unset
- `UPSTREAM_SSO` (optional): single-account fallback when the account database is missing or empty
- `UPSTREAM_COOKIE` (optional): raw-cookie fallback only when no SSO account is available
- `UPSTREAM_CF_COOKIES` (optional): extra Cloudflare cookies
- `UPSTREAM_CF_CLEARANCE` (optional): explicit `cf_clearance` token
- `UPSTREAM_CF_USER_AGENT` (optional): use same UA as clearance generation
- `UPSTREAM_URL` (default: `https://console.x.ai/v1/responses`)
- `UPSTREAM_X_CLUSTER` (default: `https://us-east-1.api.x.ai`)
- `UPSTREAM_REFERER` (optional): global fallback referer only when an account has no `team_id` or `referer`
- `UPSTREAM_ORIGIN` (default: `https://console.x.ai`)
- `UPSTREAM_USER_AGENT` (default: Chrome UA from HAR)
- `UPSTREAM_PROXY` (optional, e.g. Clash HTTP `http://127.0.0.1:7899` or SOCKS `socks5h://127.0.0.1:7898`)
- `UPSTREAM_IMPERSONATE` (optional, default `chrome136`)
- `UPSTREAM_SKIP_SSL_VERIFY` (optional, `true/false`, default `false`)
- `GATEWAY_PORT` (default: `8787`)
- `REQUEST_TIMEOUT_S` (default in `.env`: `300`; increase for long reasoning/search requests)
- `GATEWAY_MODELS` (optional CSV list; if empty, models are inferred from HAR)
- `HAR_FILE_PATH` (default: `D:\Desktop\consolex\console.x.ai.har`)

Runtime-managed values can also live in `config.toml`, seeded from `config.defaults.toml`. System environment variables still have highest priority; non-empty runtime config values override legacy `.env` values for managed keys such as `OPENAI_API_KEY`, models, timeout, proxy, upstream URL, and sampling defaults.

## Run

```bash
cd D:\Desktop\consolex
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787
```

Or:

```bash
cd D:\Desktop\consolex
python -m app
```

## Multi Account

Accounts are stored in SQLite at `accounts.sqlite3` by default. Use the admin UI to import a TXT file with one account per line:

```txt
sso-token-1,team-id-1
sso=token-2,team-id-2
```

Imported account names are assigned automatically as `1`, `2`, `3`, ... based on current order. Legacy `accounts.json` files are still readable for compatibility; when `accounts.sqlite3` does not exist and a sibling `accounts.json` exists, it is imported into SQLite on first load.

Requests use round-robin account selection. Non-streaming requests retry the next account on `401/403/429/5xx`. Streaming requests select one account per request.

## Admin UI

Open `http://127.0.0.1:8787/admin` after starting the gateway. Enter `ADMIN_KEY` to manage the gateway. If `ADMIN_KEY` is not configured, the admin UI temporarily accepts `OPENAI_API_KEY` for compatibility.

The admin page updates runtime settings in `config.toml`, including admin keys, proxy, Cloudflare cookies, model list, timeout, and default sampling values. If your deployment provides the same values as system environment variables, environment values still override runtime config.

Import a `.txt` file with one account per line:

```txt
sso-token-1,team-id-1
sso=token-2,team-id-2
```

Importing writes to `ACCOUNTS_DB` and reloads the in-memory account pool. The UI only displays masked SSO values.

Team discovery is intentionally not automatic. TXT import writes the per-account `team_id` and derives `https://console.x.ai/team/<team_id>/chat-playground` for that account. If an account object already contains `referer`, gateway requests use it first; otherwise they derive one from `team_id` and only fall back to `UPSTREAM_REFERER` when neither is present.

## Image Input And Realtime

Chat Completions accepts OpenAI-style `image_url` content blocks and maps them to Responses `input_image` blocks. Responses requests can also pass `input_image` directly. User-provided `tools`, `tool_choice`, `reasoning`, and `reasoning_effort` are preserved; when `tools` is omitted, the gateway uses the current console.x.ai default search tools with media-understanding flags from HAR traffic.

Realtime voice uses x.ai's Realtime protocol. Request a client secret through:

```bash
curl http://127.0.0.1:8787/v1/realtime/client_secrets \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"expires_after":{"seconds":300}}'
```

Then connect to `ws://127.0.0.1:8787/v1/realtime?model=grok-voice-think-fast-1.0`. WebSocket frames are passed through unchanged, including `session.update`, `conversation.item.create`, `response.create`, `response.cancel`, and audio buffer events.

This project still does not expose `/v1/images/*` or `/v1/videos/*` generation/edit endpoints.

## Docker Deployment

For an overseas server, leave `UPSTREAM_PROXY` empty. The compose file persists accounts under `data/accounts.sqlite3` inside the mounted data directory:

```bash
cp .env.example .env
docker compose up -d --build
```

## Quick Test

```bash
curl -s http://127.0.0.1:8787/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

```bash
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.3","stream":true,"messages":[{"role":"user","content":"say pong"}]}'
```

## HAR Profile Utility

```bash
python scripts/extract_har_profile.py --har D:\Desktop\consolex\console.x.ai.har --out har_profile.json
```

