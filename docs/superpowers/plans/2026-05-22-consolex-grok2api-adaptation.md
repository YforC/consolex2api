# ConsoleX Grok2API Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt selected grok2api control-plane patterns into ConsoleX without changing the upstream target away from `console.x.ai/v1/responses`.

**Architecture:** Keep the current lightweight FastAPI gateway, then incrementally add focused modules for runtime config, account state/selection, errors/SSE, batch account operations, and separated admin static assets. The adapted surface remains chat/responses only for the current ConsoleX upstream; do not add grok2api's image, video, voice, or Anthropic endpoints, and do not introduce model capability dispatch for those modes. Each phase must preserve existing `.env` and `accounts.json` compatibility until the replacement is verified.

**Tech Stack:** Python 3.10+, FastAPI, stdlib `tomllib`, existing `unittest`, `curl_cffi`.

---

### Task 1: Runtime Configuration System

**Files:**
- Create: `gateway/config.defaults.toml`
- Create: `gateway/config.toml`
- Create: `gateway/app/runtime_config.py`
- Modify: `gateway/app/config.py`
- Modify: `gateway/app/admin/routes.py`
- Test: `gateway/tests/test_gateway_core.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:
- `load_settings()` reads `OPENAI_API_KEY`, `GATEWAY_MODELS`, timeout, proxy, and sampling defaults from TOML runtime config.
- explicit environment or `.env` values still override TOML for compatibility.
- admin settings update writes `app.openai_api_key` into runtime config, not `.env`.
- user-provided `tools` and `tool_choice` in chat/responses requests remain unchanged by the migration.
- chat `reasoning_effort` is preserved and mapped to upstream `reasoning.effort`.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m unittest gateway.tests.test_gateway_core
```

Expected: new runtime config tests fail because `gateway.app.runtime_config` and TOML loading do not exist yet.

- [ ] **Step 3: Implement runtime config**

Implement a small TOML loader/writer with defaults + runtime override merge. Use environment values as the highest-precedence layer.

- [ ] **Step 4: Wire settings**

Update `load_settings()` to resolve runtime-managed values from config paths while preserving existing `.env` names.

- [ ] **Step 5: Verify**

Run:

```powershell
python -m unittest gateway.tests.test_gateway_core
python -m py_compile gateway\app\config.py gateway\app\runtime_config.py gateway\app\admin\routes.py
```

### Task 2: Account State And Selection

**Files:**
- Modify: `gateway/app/accounts.py`
- Modify: `gateway/app/upstream/xai_client.py`
- Modify: `gateway/app/admin/routes.py`
- Test: `gateway/tests/test_gateway_core.py`

- [ ] **Step 1: Write failing tests**

Add tests for `active`, `disabled`, `cooling`, `invalid`, and `failed` accounts. Verify selection skips non-selectable accounts and records last error/status after retryable upstream failures.

- [ ] **Step 2: Implement selectable state**

Add account counters, timestamps, and selection filters while keeping old JSON files readable.

- [ ] **Step 3: Wire feedback**

Make non-streaming retries mark account outcomes. For streaming, record startup failures before yielding stream chunks.

- [ ] **Step 4: Verify**

Run full unit tests and a local import parse check.

### Task 3: Unified Errors And Safe SSE

**Files:**
- Create: `gateway/app/errors.py`
- Modify: `gateway/app/main.py`
- Modify: `gateway/app/adapters/sse.py`
- Modify: `gateway/app/openai/routes.py`
- Test: `gateway/tests/test_gateway_core.py`

- [ ] **Step 1: Write failing tests**

Add tests proving JSON errors use `{"error": ...}` shape and SSE errors emit an error event followed by `data: [DONE]`.
Keep the existing `/v1/chat/completions` and `/v1/responses` payload mapping. Do not add image/video/Anthropic error surfaces.
Preserve user-provided `tools`, `tool_choice`, `reasoning`, and `reasoning_effort`; wrappers must not normalize them away.

- [ ] **Step 2: Implement error types**

Add `AppError`, `ValidationAppError`, and map existing `UpstreamError` into OpenAI-style JSON.

- [ ] **Step 3: Wrap streams**

Create shared safe SSE wrappers for chat and responses.

- [ ] **Step 4: Verify**

Run unit tests and py_compile.

### Task 4: Batch Import, Disable, Refresh

**Files:**
- Modify: `gateway/app/admin/routes.py`
- Modify: `gateway/app/accounts.py`
- Test: `gateway/tests/test_gateway_core.py`

- [ ] **Step 1: Write failing tests**

Add tests for bulk add, replace, delete, disable, enable, and refresh endpoint behavior.

- [ ] **Step 2: Implement admin account APIs**

Add `/admin/api/accounts/add`, `/admin/api/accounts/replace`, `/admin/api/accounts/delete`, `/admin/api/accounts/disabled`, and `/admin/api/accounts/refresh`.

- [ ] **Step 3: Implement lightweight refresh**

Use a small authenticated upstream check when possible; otherwise record a structured skipped/error state.

- [ ] **Step 4: Verify**

Run unit tests and manually inspect admin API summaries.

### Task 5: Admin UI Separation

**Files:**
- Create: `gateway/app/statics/admin/index.html`
- Create: `gateway/app/statics/admin/admin.css`
- Create: `gateway/app/statics/admin/admin.js`
- Modify: `gateway/app/admin/routes.py`
- Test: `gateway/tests/test_gateway_core.py`

- [ ] **Step 1: Write failing tests**

Add tests proving `/admin` is served from static files and the large inline `_ADMIN_HTML` is no longer needed.

- [ ] **Step 2: Extract current UI**

Move HTML, CSS, and JS into static files without changing visible behavior.

- [ ] **Step 3: Add UI for new APIs**

Add runtime config, account state filters, batch disable/enable, and refresh controls.
Do not add image/video/cache media pages from grok2api unless explicitly requested later.

- [ ] **Step 4: Verify**

Run unit tests and `Invoke-WebRequest` against `/admin` to confirm the new assets load.
