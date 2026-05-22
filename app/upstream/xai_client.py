"""HTTP client for upstream console.x.ai /v1/responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from curl_cffi import requests as crequests

from ..adapters.responses import build_responses_payload
from ..accounts import Account, AccountPool, is_retryable_status, record_account_result
from ..config import Settings
from .realtime import REALTIME_CLIENT_SECRET_URL


_ACCOUNT_POOL_CACHE: dict[tuple[str, str, int | None, int | None], AccountPool] = {}


class UpstreamError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502, details: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _account_cookie(settings: Settings, account: Account) -> str:
    cookie = account.cookie_header
    if settings.upstream_cf_clearance:
        cookie += f"; cf_clearance={settings.upstream_cf_clearance}"
    if settings.upstream_cf_cookies:
        extra = settings.upstream_cf_cookies.strip("; ")
        if extra:
            cookie += f"; {extra}"
    return cookie


def _upstream_headers(settings: Settings, account: Account | None = None) -> dict[str, str]:
    headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en-GB;q=0.8,en;q=0.7",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": settings.upstream_origin,
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": account.referer if account is not None and account.referer else settings.upstream_referer,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": settings.upstream_user_agent,
        "x-cluster": settings.upstream_cluster,
    }
    if account is not None:
        headers["cookie"] = _account_cookie(settings, account)
    elif settings.cookie_header:
        headers["cookie"] = settings.cookie_header
    return headers


def _voice_referer(settings: Settings, account: Account) -> str:
    if account.team_id:
        return f"https://console.x.ai/team/{account.team_id}/voice/voice-agent"
    if account.referer:
        return account.referer.replace("/chat-playground", "/voice/voice-agent")
    return settings.upstream_referer


def _realtime_headers(settings: Settings, account: Account) -> dict[str, str]:
    headers = _upstream_headers(settings, account)
    headers["referer"] = _voice_referer(settings, account)
    return headers


def _normalize_proxy_url(url: str) -> str:
    if not url:
        return url
    low = url.lower()
    if low.startswith("socks://"):
        return "socks5h://" + url[len("socks://") :]
    if low.startswith("socks5://"):
        return "socks5h://" + url[len("socks5://") :]
    if low.startswith("socks4://"):
        return "socks4a://" + url[len("socks4://") :]
    return url


def _session_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "impersonate": settings.upstream_impersonate or "chrome136",
        "verify": (not settings.upstream_skip_ssl_verify),
    }
    if settings.upstream_proxy:
        proxy_url = _normalize_proxy_url(settings.upstream_proxy)
        if proxy_url.startswith("socks"):
            kwargs["proxy"] = proxy_url
        else:
            kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
    return kwargs


def _account_pool(settings: Settings) -> AccountPool:
    mtime_ns: int | None = None
    size: int | None = None
    if settings.accounts_file:
        try:
            stat = Path(settings.accounts_file).stat()
            mtime_ns = stat.st_mtime_ns
            size = stat.st_size
        except OSError:
            pass

    key = (settings.accounts_file, settings.upstream_sso, mtime_ns, size)
    pool = _ACCOUNT_POOL_CACHE.get(key)
    if pool is None:
        _ACCOUNT_POOL_CACHE.clear()
        pool = AccountPool.from_file(settings.accounts_file, fallback_sso=settings.upstream_sso)
        _ACCOUNT_POOL_CACHE[key] = pool
    return pool


def _record_result(settings: Settings, account: Account, *, status_code: int | None, error: str = "") -> None:
    if not settings.accounts_file:
        return
    if record_account_result(settings.accounts_file, account, status_code=status_code, error=error):
        _ACCOUNT_POOL_CACHE.clear()


def _raise_for_status(resp: Any) -> None:
    if resp.status_code < 400:
        return
    text = str(resp.text)[:1200]
    raise UpstreamError(
        f"Upstream request failed with status {resp.status_code}",
        status_code=resp.status_code,
        details=text,
    )


async def check_account_health(settings: Settings, account: Account) -> tuple[int | None, str]:
    payload = build_responses_payload(
        model=settings.model_list[0] if settings.model_list else "grok-4.3",
        input_val="ping",
        instructions=None,
        stream=False,
        temperature=None,
        top_p=None,
        max_output_tokens=16,
        tools=None,
        tool_choice=None,
        tools_enabled=settings.tools_enabled,
        web_search_enabled=settings.web_search_enabled,
        x_search_enabled=settings.x_search_enabled,
    )
    kwargs = _session_kwargs(settings)
    async with crequests.AsyncSession(**kwargs) as session:
        try:
            resp = await session.post(
                settings.upstream_url,
                headers=_upstream_headers(settings, account),
                data=json.dumps(payload).encode("utf-8"),
                timeout=min(settings.request_timeout_s, 30),
            )
        except Exception as exc:
            return None, str(exc)
    if resp.status_code < 400:
        return resp.status_code, ""
    return resp.status_code, str(resp.text)[:1200]


async def create_response_json(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    kwargs = _session_kwargs(settings)
    pool = _account_pool(settings)
    last_exc: UpstreamError | None = None

    for _ in range(max(1, len(pool))):
        account = pool.next_account()
        async with crequests.AsyncSession(**kwargs) as session:
            try:
                resp = await session.post(
                    settings.upstream_url,
                    headers=_upstream_headers(settings, account),
                    data=json.dumps(payload).encode("utf-8"),
                    timeout=settings.request_timeout_s,
                )
            except Exception as exc:
                last_exc = UpstreamError(f"Upstream network error: {exc}")
                _record_result(settings, account, status_code=None, error=str(exc))
                continue
        try:
            _raise_for_status(resp)
        except UpstreamError as exc:
            last_exc = exc
            _record_result(settings, account, status_code=exc.status_code, error=exc.details or str(exc))
            if is_retryable_status(exc.status_code) and len(pool) > 1:
                continue
            raise
        _record_result(settings, account, status_code=resp.status_code)
        break
    else:
        raise last_exc or UpstreamError("No upstream accounts available")

    try:
        return json.loads(resp.text)
    except ValueError as exc:
        raise UpstreamError("Upstream returned non-JSON response", details=resp.text[:800]) from exc


async def create_realtime_client_secret(settings: Settings, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    kwargs = _session_kwargs(settings)
    pool = _account_pool(settings)
    account = pool.next_account()
    body = payload if isinstance(payload, dict) else {"expires_after": {"seconds": 300}}
    async with crequests.AsyncSession(**kwargs) as session:
        try:
            resp = await session.post(
                REALTIME_CLIENT_SECRET_URL,
                headers=_realtime_headers(settings, account),
                data=json.dumps(body).encode("utf-8"),
                timeout=min(settings.request_timeout_s, 30),
            )
        except Exception as exc:
            _record_result(settings, account, status_code=None, error=str(exc))
            raise UpstreamError(f"Realtime client secret network error: {exc}") from exc
    try:
        _raise_for_status(resp)
    except UpstreamError as exc:
        _record_result(settings, account, status_code=exc.status_code, error=exc.details or str(exc))
        raise
    _record_result(settings, account, status_code=resp.status_code)
    try:
        return json.loads(resp.text)
    except ValueError as exc:
        raise UpstreamError("Realtime client secret returned non-JSON response", details=resp.text[:800]) from exc


async def stream_response_events(
    settings: Settings,
    payload: dict[str, Any],
) -> AsyncIterator[str]:
    kwargs = _session_kwargs(settings)
    pool = _account_pool(settings)
    account = pool.next_account()
    async with crequests.AsyncSession(**kwargs) as session:
        try:
            resp = await session.post(
                settings.upstream_url,
                headers=_upstream_headers(settings, account),
                data=json.dumps(payload).encode("utf-8"),
                timeout=settings.request_timeout_s,
                stream=True,
            )
            if resp.status_code >= 400:
                body = resp.text
                raise UpstreamError(
                    f"Upstream request failed with status {resp.status_code}",
                    status_code=resp.status_code,
                    details=str(body)[:1200],
                )

            async for line in resp.aiter_lines():
                if line is None:
                    continue
                if isinstance(line, bytes):
                    yield line.decode("utf-8", errors="replace")
                else:
                    yield str(line)
            resp.close()
        except UpstreamError:
            raise
        except Exception as exc:
            raise UpstreamError(f"Upstream stream network error: {exc}") from exc
