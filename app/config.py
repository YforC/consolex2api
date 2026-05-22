"""Runtime configuration for gateway."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import runtime_config


DEFAULT_MODELS = (
    "grok-4.3",
    "grok-build-0.1",
    "grok-voice-think-fast-1.0",
    "grok-4.20-0309-non-reasoning",
    "grok-4.20-0309-reasoning",
    "grok-4.20-multi-agent-0309",
)

_ENV_CACHE: dict[str, str] | None = None


def _dotenv_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def _load_dotenv_values() -> dict[str, str]:
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE

    values: dict[str, str] = {}
    path = _dotenv_path()
    if not path.exists():
        _ENV_CACHE = values
        return values

    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    _ENV_CACHE = values
    return values


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    return _load_dotenv_values().get(name, default)


def env_source(name: str) -> str:
    if os.getenv(name) is not None:
        return "environment"
    if name in _load_dotenv_values():
        return "dotenv"
    return "unset"


def setting_source(env_name: str, config_key: str) -> str:
    if os.getenv(env_name) is not None:
        return "environment"
    if runtime_config.runtime_has_value(config_key):
        return "runtime_config"
    if env_name in _load_dotenv_values():
        return "dotenv"
    return "unset"


def _runtime_setting(env_name: str, config_key: str, default: Any = "") -> Any:
    value = os.getenv(env_name)
    if value is not None:
        return value

    marker = object()
    configured = runtime_config.runtime_value(config_key, marker)
    if configured is not marker:
        if isinstance(configured, str):
            if configured.strip():
                return configured
        elif isinstance(configured, list):
            if configured:
                return configured
        elif configured is not None:
            return configured

    dotenv = _load_dotenv_values().get(env_name)
    if dotenv is not None:
        return dotenv
    return default


def set_dotenv_value(name: str, value: str, *, path: Path | None = None) -> None:
    global _ENV_CACHE
    dotenv = path or _dotenv_path()
    dotenv.parent.mkdir(parents=True, exist_ok=True)
    lines = dotenv.read_text(encoding="utf-8-sig").splitlines() if dotenv.exists() else []

    updated = False
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _ = stripped.split("=", 1)
            if key.strip() == name:
                next_lines.append(f"{name}={value}")
                updated = True
                continue
        next_lines.append(line)
    if not updated:
        next_lines.append(f"{name}={value}")

    tmp_path = dotenv.with_suffix(dotenv.suffix + ".tmp")
    tmp_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    tmp_path.replace(dotenv)
    _ENV_CACHE = None


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _extract_cookie_value(cookie_header: str, name: str) -> str:
    if not cookie_header:
        return ""
    match = re.search(rf"(?:^|;\s*){re.escape(name)}=([^;]*)", cookie_header)
    return match.group(1) if match else ""


def _accounts_file_has_sso(path: str) -> bool:
    if not path:
        return False
    try:
        from .accounts import load_account_records

        records = load_account_records(path)
    except (OSError, ValueError):
        return False
    return any(str(item.get("sso", "")).strip() for item in records)


def collect_models_from_har(har_path: str) -> list[str]:
    """Extract model names used in /v1/responses requests from HAR."""
    path = Path(har_path)
    if not path.exists():
        return list(DEFAULT_MODELS)

    try:
        with path.open("r", encoding="utf-8") as f:
            har = json.load(f)
    except (OSError, ValueError):
        return list(DEFAULT_MODELS)

    models: set[str] = set()
    for entry in har.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        url = str(req.get("url", ""))
        if "/v1/responses" not in url:
            continue
        body = req.get("postData", {}).get("text", "")
        if not body:
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        model = payload.get("model")
        if isinstance(model, str) and model.strip():
            models.add(model.strip())

    models.update(DEFAULT_MODELS)
    return sorted(models)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    openai_api_key: str
    upstream_url: str
    upstream_cookie: str
    upstream_sso: str
    upstream_cluster: str
    upstream_referer: str
    upstream_origin: str
    upstream_user_agent: str
    upstream_proxy: str
    upstream_impersonate: str
    upstream_skip_ssl_verify: bool
    upstream_cf_cookies: str
    upstream_cf_clearance: str
    accounts_file: str
    default_temperature: float
    default_top_p: float
    request_timeout_s: float
    model_list: list[str]
    admin_key: str = ""
    tools_enabled: bool = True
    default_reasoning_effort: str = ""

    @property
    def cookie_header(self) -> str:
        # Align with grok2api strategy:
        # 1) Prefer SSO token and synthesize cookie as "sso + sso-rw"
        # 2) Optionally append CF cookies/clearance
        # 3) Fallback to raw cookie only when SSO is absent
        sso = self.upstream_sso.strip()
        if sso:
            tok = sso[4:] if sso.startswith("sso=") else sso
            cookie = f"sso={tok}; sso-rw={tok}"

            extra = self.upstream_cf_cookies.strip()
            clearance = self.upstream_cf_clearance.strip() or _extract_cookie_value(
                extra,
                "cf_clearance",
            )
            if clearance and extra:
                if re.search(r"(?:^|;\s*)cf_clearance=", extra):
                    extra = re.sub(
                        r"(^|;\s*)cf_clearance=[^;]*",
                        r"\1cf_clearance=" + clearance,
                        extra,
                        count=1,
                    )
                else:
                    extra = f"{extra.rstrip('; ')}; cf_clearance={clearance}"
            elif clearance:
                extra = f"cf_clearance={clearance}"

            if extra:
                cookie += f"; {extra.strip('; ')}"
            return cookie

        if self.upstream_cookie.strip():
            return self.upstream_cookie.strip()
        return ""

    def has_upstream_auth(self) -> bool:
        return bool(self.cookie_header) or _accounts_file_has_sso(self.accounts_file)


def load_settings() -> Settings:
    model_raw = _runtime_setting("GATEWAY_MODELS", "models.ids", "")
    if isinstance(model_raw, list):
        model_list = [str(item).strip() for item in model_raw if str(item).strip()]
    else:
        model_csv = str(model_raw or "").strip()
        model_list = _split_csv(model_csv) if model_csv else []
    if model_list:
        pass
    else:
        har_path = _env(
            "HAR_FILE_PATH",
            r"D:\Desktop\consolex\console.x.ai.har",
        )
        model_list = collect_models_from_har(har_path)

    skip_ssl_raw = str(_runtime_setting("UPSTREAM_SKIP_SSL_VERIFY", "upstream.skip_ssl_verify", "")).strip().lower()
    skip_ssl = skip_ssl_raw in {"1", "true", "yes", "on"}
    tools_enabled_raw = str(_runtime_setting("GATEWAY_TOOLS_ENABLED", "generation.tools_enabled", "true")).strip().lower()
    tools_enabled = tools_enabled_raw not in {"0", "false", "no", "off"}
    default_reasoning_effort = str(
        _runtime_setting("DEFAULT_REASONING_EFFORT", "generation.reasoning_effort", "")
    ).strip()

    upstream_cf_cookies = (
        str(_runtime_setting("UPSTREAM_CF_COOKIES", "upstream.cf_cookies", "")).strip()
        or _env("PROXY_CF_COOKIES", "").strip()
    )
    upstream_cf_clearance = (
        str(_runtime_setting("UPSTREAM_CF_CLEARANCE", "upstream.cf_clearance", "")).strip()
        or _env("PROXY_CF_CLEARANCE", "").strip()
    )
    upstream_user_agent = (
        _env("UPSTREAM_CF_USER_AGENT", "").strip()
        or str(_runtime_setting("UPSTREAM_USER_AGENT", "upstream.user_agent", "")).strip()
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    )

    return Settings(
        host=_env("GATEWAY_HOST", "0.0.0.0"),
        port=int(_env("GATEWAY_PORT", "8787")),
        openai_api_key=str(_runtime_setting("OPENAI_API_KEY", "app.openai_api_key", "")).strip(),
        upstream_url=str(_runtime_setting("UPSTREAM_URL", "upstream.url", "https://console.x.ai/v1/responses")).strip(),
        upstream_cookie=str(_runtime_setting("UPSTREAM_COOKIE", "upstream.cookie", "")).strip(),
        upstream_sso=str(_runtime_setting("UPSTREAM_SSO", "upstream.sso", "")).strip(),
        upstream_cluster=str(_runtime_setting("UPSTREAM_X_CLUSTER", "upstream.cluster", "https://us-east-1.api.x.ai")).strip(),
        upstream_referer=str(_runtime_setting("UPSTREAM_REFERER", "upstream.referer", "")).strip(),
        upstream_origin=str(_runtime_setting("UPSTREAM_ORIGIN", "upstream.origin", "https://console.x.ai")).strip(),
        upstream_user_agent=upstream_user_agent,
        upstream_proxy=str(_runtime_setting("UPSTREAM_PROXY", "upstream.proxy", "")).strip(),
        upstream_impersonate=str(_runtime_setting("UPSTREAM_IMPERSONATE", "upstream.impersonate", "chrome136")).strip(),
        upstream_skip_ssl_verify=skip_ssl,
        upstream_cf_cookies=upstream_cf_cookies,
        upstream_cf_clearance=upstream_cf_clearance,
        accounts_file=_env(
            "ACCOUNTS_DB",
            _env("ACCOUNTS_FILE", str(Path(__file__).resolve().parents[1] / "accounts.sqlite3")),
        ).strip(),
        default_temperature=float(_runtime_setting("DEFAULT_TEMPERATURE", "generation.temperature", "0.7")),
        default_top_p=float(_runtime_setting("DEFAULT_TOP_P", "generation.top_p", "0.95")),
        request_timeout_s=float(_runtime_setting("REQUEST_TIMEOUT_S", "chat.timeout", "120")),
        model_list=model_list,
        admin_key=str(_runtime_setting("ADMIN_KEY", "app.admin_key", "")).strip(),
        tools_enabled=tools_enabled,
        default_reasoning_effort=default_reasoning_effort,
    )


def model_object(model_id: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "object": "model",
        "owned_by": "xai",
    }
