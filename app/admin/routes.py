"""Small admin UI for importing SSO accounts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from ..accounts import (
    Account,
    AccountPool,
    load_account_records,
    record_account_event,
    referer_from_team_id,
    status_from_result,
    write_account_records,
)
from ..auth import verify_admin_key
from ..config import load_settings, setting_source
from .. import config as config_module
from ..runtime_config import runtime_config_path, set_runtime_config_value
from ..upstream.xai_client import _ACCOUNT_POOL_CACHE, check_account_health


router = APIRouter(prefix="/admin", tags=["admin"])
_REFRESH_CANCELLED: set[str] = set()


def admin_static_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "statics" / "admin" / name


def _normalize_sso(raw: str) -> str:
    token = raw.strip()
    if token.startswith("sso="):
        token = token[4:].strip()
    return token


def _parse_account_line(line: str) -> tuple[str, str]:
    sso_part, sep, team_part = line.partition(",")
    sso = _normalize_sso(sso_part)
    team_id = team_part.strip() if sep else ""
    return sso, team_id


def parse_sso_txt(text: str) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        token, team_id = _parse_account_line(line)
        key = (token, team_id)
        if not token or key in seen:
            continue
        seen.add(key)
        accounts.append(
            {
                "name": str(len(accounts) + 1),
                "sso": token,
                "team_id": team_id,
                "referer": referer_from_team_id(team_id),
                "status": "active",
                "last_checked_at": 0,
                "last_error": "",
            }
        )
    return accounts


def mask_sso(sso: str) -> str:
    token = _normalize_sso(sso)
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def mask_secret(secret: str) -> str:
    value = (secret or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def classify_account_error(status_code: int | None, error: str) -> str:
    text = str(error or "").lower()
    if status_code in {401, 403} or "unauthorized" in text or "forbidden" in text:
        return "auth"
    if status_code == 429 or "rate limit" in text or "too many request" in text:
        return "rate_limit"
    if any(part in text for part in ("cloudflare", "cf_clearance", "challenge", "turnstile")):
        return "cloudflare"
    if any(part in text for part in ("invalid argument", "invalid_request", "bad request", "schema", "tool_choice")):
        return "request"
    if any(part in text for part in ("team", "organization", "workspace")):
        return "team"
    if any(part in text for part in ("timeout", "proxy", "connect", "connection", "dns", "tls", "ssl")):
        return "network"
    if status_code is None:
        return "network" if text else ""
    if status_code >= 400 or text:
        return "upstream"
    return ""


def _accounts_path() -> Path:
    settings = load_settings()
    return Path(settings.accounts_file)


def _load_account_summary() -> dict[str, Any]:
    settings = load_settings()
    pool = AccountPool.from_file(settings.accounts_file, fallback_sso="")
    effective_source = "accounts_file" if pool.accounts else "none"
    if not pool.accounts and settings.upstream_sso.strip():
        effective_source = "env_fallback"
    status_counts: dict[str, int] = {}
    total_use_count = 0
    total_fail_count = 0
    account_rows = []
    problem_count = 0
    for account in pool.accounts:
        status = (account.status or "pending").strip().lower() or "pending"
        status_counts[status] = status_counts.get(status, 0) + 1
        total_use_count += account.use_count
        total_fail_count += account.fail_count
        error_category = classify_account_error(None, account.last_error)
        if status in {"cooling", "invalid", "expired", "failed"} or (status != "disabled" and error_category):
            problem_count += 1
        account_rows.append(
            {
                "name": account.name,
                "sso": mask_sso(account.sso),
                "team_id": account.team_id,
                "referer": account.referer,
                "status": account.status,
                "last_checked_at": account.last_checked_at,
                "last_error": account.last_error,
                "error_category": error_category,
                "use_count": account.use_count,
                "fail_count": account.fail_count,
                "last_used_at": account.last_used_at,
            }
        )
    return {
        "accounts_file": settings.accounts_file,
        "effective_source": effective_source,
        "env_fallback_configured": bool(settings.upstream_sso.strip()),
        "count": len(pool.accounts),
        "selectable_count": len(pool.selectable_accounts),
        "problem_count": problem_count,
        "status_counts": status_counts,
        "total_use_count": total_use_count,
        "total_fail_count": total_fail_count,
        "accounts": account_rows,
    }


def _load_accounts_raw() -> list[dict[str, Any]]:
    return load_account_records(str(_accounts_path()))


def _load_gateway_settings_summary() -> dict[str, Any]:
    settings = load_settings()
    values = {
        "app.openai_api_key": "",
        "app.admin_key": "",
        "upstream.url": settings.upstream_url,
        "upstream.cluster": settings.upstream_cluster,
        "upstream.origin": settings.upstream_origin,
        "upstream.referer": settings.upstream_referer,
        "upstream.user_agent": settings.upstream_user_agent,
        "upstream.proxy": settings.upstream_proxy,
        "upstream.impersonate": settings.upstream_impersonate,
        "upstream.skip_ssl_verify": settings.upstream_skip_ssl_verify,
        "upstream.cf_cookies": settings.upstream_cf_cookies,
        "upstream.cf_clearance": "",
        "models.ids": settings.model_list,
        "chat.timeout": settings.request_timeout_s,
        "generation.temperature": settings.default_temperature,
        "generation.top_p": settings.default_top_p,
    }
    masked_values = {
        "app.openai_api_key": mask_secret(settings.openai_api_key),
        "app.admin_key": mask_secret(settings.admin_key),
        "upstream.cf_clearance": mask_secret(settings.upstream_cf_clearance),
    }
    return {
        "openai_api_key_configured": bool(settings.openai_api_key.strip()),
        "openai_api_key_masked": mask_secret(settings.openai_api_key),
        "openai_api_key_source": setting_source("OPENAI_API_KEY", "app.openai_api_key"),
        "admin_key_configured": bool(settings.admin_key.strip()),
        "admin_key_source": setting_source("ADMIN_KEY", "app.admin_key"),
        "runtime_config_path": str(runtime_config_path()),
        "values": values,
        "masked_values": masked_values,
        "sources": {
            "app.openai_api_key": setting_source("OPENAI_API_KEY", "app.openai_api_key"),
            "app.admin_key": setting_source("ADMIN_KEY", "app.admin_key"),
            "upstream.proxy": setting_source("UPSTREAM_PROXY", "upstream.proxy"),
            "upstream.cf_cookies": setting_source("UPSTREAM_CF_COOKIES", "upstream.cf_cookies"),
            "upstream.cf_clearance": setting_source("UPSTREAM_CF_CLEARANCE", "upstream.cf_clearance"),
            "models.ids": setting_source("GATEWAY_MODELS", "models.ids"),
            "chat.timeout": setting_source("REQUEST_TIMEOUT_S", "chat.timeout"),
        },
        "fields": _settings_fields(),
    }


def _settings_fields() -> list[dict[str, Any]]:
    return [
        {
            "id": "app",
            "label": "访问控制",
            "fields": [
                {"key": "app.openai_api_key", "label": "网关 API Key", "type": "password"},
                {"key": "app.admin_key", "label": "Admin Key", "type": "password"},
            ],
        },
        {
            "id": "upstream",
            "label": "上游请求",
            "fields": [
                {"key": "upstream.url", "label": "上游 URL", "type": "text"},
                {"key": "upstream.cluster", "label": "X Cluster", "type": "text"},
                {"key": "upstream.origin", "label": "Origin", "type": "text"},
                {"key": "upstream.referer", "label": "全局 Referer 兜底", "type": "text"},
                {"key": "upstream.user_agent", "label": "User-Agent", "type": "textarea"},
                {"key": "upstream.proxy", "label": "代理", "type": "text"},
                {"key": "upstream.impersonate", "label": "浏览器指纹", "type": "text"},
                {"key": "upstream.skip_ssl_verify", "label": "跳过 SSL 校验", "type": "bool"},
                {"key": "upstream.cf_cookies", "label": "Cloudflare Cookies", "type": "textarea"},
                {"key": "upstream.cf_clearance", "label": "cf_clearance", "type": "password"},
            ],
        },
        {
            "id": "models",
            "label": "模型与默认参数",
            "fields": [
                {"key": "models.ids", "label": "模型列表", "type": "list"},
                {"key": "chat.timeout", "label": "请求超时秒数", "type": "number"},
                {"key": "generation.temperature", "label": "默认 Temperature", "type": "number"},
                {"key": "generation.top_p", "label": "默认 Top P", "type": "number"},
            ],
        },
    ]


_ALLOWED_SETTING_KEYS = {
    field["key"]
    for group in _settings_fields()
    for field in group["fields"]
}
_SECRET_SETTING_KEYS = {"app.openai_api_key", "app.admin_key", "upstream.cf_clearance"}


def _coerce_setting_value(key: str, value: Any) -> Any:
    if key == "models.ids":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [part.strip() for part in str(value or "").splitlines() if part.strip()]
    if key in {"chat.timeout", "generation.temperature", "generation.top_p"}:
        return float(value)
    if key == "upstream.skip_ssl_verify":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return str(value or "").strip()


def _write_accounts(accounts: list[dict[str, Any]]) -> None:
    write_account_records(str(_accounts_path()), accounts)
    _ACCOUNT_POOL_CACHE.clear()


def _account_key(item: dict[str, Any]) -> tuple[str, str]:
    return (_normalize_sso(str(item.get("sso", ""))), str(item.get("team_id", "")).strip())


def _payload_account_keys(payload: dict[str, Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    raw_accounts = payload.get("accounts", [])
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            key = _account_key(item)
            if key[0]:
                keys.add(key)
    text = str(payload.get("text", "") or "")
    for item in parse_sso_txt(text):
        key = _account_key(item)
        if key[0]:
            keys.add(key)
    return keys


def _payload_account_indexes(payload: dict[str, Any], total: int) -> set[int]:
    indexes: set[int] = set()
    raw_indexes = payload.get("indexes", [])
    if not isinstance(raw_indexes, list):
        return indexes
    for value in raw_indexes:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < total:
            indexes.add(index)
    return indexes


def _renumber_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for idx, item in enumerate(accounts):
        item["name"] = str(idx + 1)
    return accounts


def _selected_indexes(payload: dict[str, Any], accounts: list[dict[str, Any]]) -> list[int]:
    keys = _payload_account_keys(payload)
    indexes = _payload_account_indexes(payload, len(accounts))
    selected = [
        idx
        for idx, account in enumerate(accounts)
        if _account_key(account) in keys or idx in indexes
    ]
    return selected


def _account_from_record(account: dict[str, Any], idx: int) -> Account:
    team_id = str(account.get("team_id", ""))
    return Account(
        name=str(account.get("name") or idx + 1),
        sso=str(account.get("sso", "")),
        team_id=team_id,
        referer=str(account.get("referer", "")) or referer_from_team_id(team_id),
        status=str(account.get("status", "pending")),
    )


async def _refresh_account_record(settings: Any, account: dict[str, Any], idx: int) -> dict[str, Any]:
    account_obj = _account_from_record(account, idx)
    status_code, error = await check_account_health(settings, account_obj)
    account["status"] = status_from_result(status_code)
    account["last_error"] = "" if status_code is not None and status_code < 400 else str(error or "")
    account["last_status_code"] = status_code or 0
    account["error_category"] = classify_account_error(status_code, account["last_error"])
    account["last_checked_at"] = time.time()
    record_account_event(
        str(_accounts_path()),
        account_obj,
        status=account["status"],
        status_code=status_code,
        error=account["last_error"],
        kind="refresh",
    )
    return account


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def admin_page() -> FileResponse:
    return FileResponse(admin_static_path("index.html"))


@router.get("/assets/{asset_name}", include_in_schema=False)
async def admin_asset(asset_name: str) -> FileResponse:
    allowed = {"admin.css": "text/css", "admin.js": "application/javascript"}
    if asset_name not in allowed:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(admin_static_path(asset_name), media_type=allowed[asset_name])


@router.get("/api/accounts", dependencies=[Depends(verify_admin_key)])
async def admin_accounts() -> JSONResponse:
    return JSONResponse(_load_account_summary())


@router.get("/api/settings", dependencies=[Depends(verify_admin_key)])
async def admin_settings() -> JSONResponse:
    return JSONResponse(_load_gateway_settings_summary())


@router.put("/api/settings", dependencies=[Depends(verify_admin_key)])
async def update_admin_settings(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    values = payload.get("values")
    if not isinstance(values, dict):
        openai_api_key = str(payload.get("openai_api_key", "")).strip()
        if not openai_api_key:
            raise HTTPException(status_code=400, detail="OPENAI_API_KEY cannot be empty.")
        values = {"app.openai_api_key": openai_api_key}
    for key, value in values.items():
        if key not in _ALLOWED_SETTING_KEYS:
            raise HTTPException(status_code=400, detail=f"Unsupported setting: {key}")
        coerced = _coerce_setting_value(key, value)
        if key in _SECRET_SETTING_KEYS and not str(coerced or "").strip():
            continue
        set_runtime_config_value(key, coerced)
    config_module._ENV_CACHE = None
    return JSONResponse(_load_gateway_settings_summary())


@router.post("/api/accounts/import", dependencies=[Depends(verify_admin_key)])
async def import_accounts(payload: dict[str, str] = Body(...)) -> JSONResponse:
    text = payload.get("text", "")
    accounts = parse_sso_txt(text)
    if not accounts:
        raise HTTPException(status_code=400, detail="No valid SSO tokens found in TXT content.")
    _write_accounts(accounts)
    return JSONResponse(_load_account_summary())


@router.post("/api/accounts/add", dependencies=[Depends(verify_admin_key)])
async def add_accounts(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    incoming = parse_sso_txt(str(payload.get("text", "") or ""))
    if not incoming:
        raise HTTPException(status_code=400, detail="No valid SSO tokens found in TXT content.")
    existing = _load_accounts_raw()
    seen = {_account_key(item) for item in existing}
    added = 0
    for account in incoming:
        key = _account_key(account)
        if key in seen:
            continue
        account["name"] = str(len(existing) + 1)
        existing.append(account)
        seen.add(key)
        added += 1
    _write_accounts(_renumber_accounts(existing))
    summary = _load_account_summary()
    summary["added"] = added
    return JSONResponse(summary)


@router.post("/api/accounts/disabled", dependencies=[Depends(verify_admin_key)])
async def toggle_accounts_disabled(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    disabled = bool(payload.get("disabled", True))
    accounts = _load_accounts_raw()
    keys = _payload_account_keys(payload)
    indexes = _payload_account_indexes(payload, len(accounts))
    if not keys and not indexes:
        raise HTTPException(status_code=400, detail="No account keys provided.")
    patched = 0
    for idx, account in enumerate(accounts):
        if _account_key(account) not in keys and idx not in indexes:
            continue
        account["status"] = "disabled" if disabled else "active"
        if not disabled:
            account["last_error"] = ""
        patched += 1
    _write_accounts(accounts)
    summary = _load_account_summary()
    summary["patched"] = patched
    return JSONResponse(summary)


@router.post("/api/accounts/delete", dependencies=[Depends(verify_admin_key)])
async def delete_accounts(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    accounts = _load_accounts_raw()
    keys = _payload_account_keys(payload)
    indexes = _payload_account_indexes(payload, len(accounts))
    if not keys and not indexes:
        raise HTTPException(status_code=400, detail="No account keys provided.")
    kept = [
        account
        for idx, account in enumerate(accounts)
        if _account_key(account) not in keys and idx not in indexes
    ]
    _write_accounts(_renumber_accounts(kept))
    summary = _load_account_summary()
    summary["deleted"] = len(accounts) - len(kept)
    return JSONResponse(summary)


@router.post("/api/accounts/edit", dependencies=[Depends(verify_admin_key)])
async def edit_account(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    accounts = _load_accounts_raw()
    try:
        index = int(payload.get("index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Valid account index is required.")
    if index < 0 or index >= len(accounts):
        raise HTTPException(status_code=404, detail="Account not found.")

    account = accounts[index]
    sso = _normalize_sso(str(payload.get("sso", "") or ""))
    team_id = str(payload.get("team_id", account.get("team_id", "")) or "").strip()
    status = str(payload.get("status", account.get("status", "pending")) or "pending").strip()
    if sso:
        account["sso"] = sso
    account["team_id"] = team_id
    account["referer"] = referer_from_team_id(team_id)
    account["status"] = status
    if status == "active":
        account["last_error"] = ""
    _write_accounts(_renumber_accounts(accounts))
    return JSONResponse(_load_account_summary())


@router.post("/api/accounts/refresh", dependencies=[Depends(verify_admin_key)])
async def refresh_accounts(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    settings = load_settings()
    accounts = _load_accounts_raw()
    selected = _selected_indexes(payload, accounts)
    if not selected:
        raise HTTPException(status_code=400, detail="No account keys provided.")
    patched = 0
    for idx in selected:
        await _refresh_account_record(settings, accounts[idx], idx)
        patched += 1
    _write_accounts(accounts)
    summary = _load_account_summary()
    summary["refreshed"] = patched
    return JSONResponse(summary)


@router.post("/api/accounts/refresh/stream", dependencies=[Depends(verify_admin_key)])
async def stream_refresh_accounts(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    settings = load_settings()
    accounts = _load_accounts_raw()
    selected = _selected_indexes(payload, accounts)
    if not selected:
        raise HTTPException(status_code=400, detail="No account keys provided.")
    job_id = str(payload.get("job_id") or f"refresh-{int(time.time() * 1000)}")

    async def events():
        total = len(selected)
        done = 0
        yield _sse_event("start", {"job_id": job_id, "total": total})
        try:
            for idx in selected:
                if job_id in _REFRESH_CANCELLED:
                    yield _sse_event("cancelled", {"job_id": job_id, "done": done, "total": total})
                    return
                await _refresh_account_record(settings, accounts[idx], idx)
                done += 1
                _write_accounts(accounts)
                yield _sse_event(
                    "progress",
                    {
                        "job_id": job_id,
                        "done": done,
                        "total": total,
                        "index": idx,
                        "name": accounts[idx].get("name", str(idx + 1)),
                        "status": accounts[idx].get("status", ""),
                        "status_code": accounts[idx].get("last_status_code", 0),
                        "error_category": accounts[idx].get("error_category", ""),
                        "last_error": accounts[idx].get("last_error", ""),
                    },
                )
            yield _sse_event("complete", {"job_id": job_id, "done": done, "total": total})
        finally:
            _REFRESH_CANCELLED.discard(job_id)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/api/accounts/refresh/cancel", dependencies=[Depends(verify_admin_key)])
async def cancel_refresh_accounts(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    job_id = str(payload.get("job_id", "")).strip()
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required.")
    _REFRESH_CANCELLED.add(job_id)
    return JSONResponse({"cancelled": True, "job_id": job_id})

