"""Runtime TOML configuration for gateway-managed settings."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config.defaults.toml"


def runtime_config_path() -> Path:
    raw = os.getenv("GATEWAY_CONFIG_FILE", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "config.toml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data if isinstance(data, dict) else {}


def load_runtime_config(
    *,
    defaults_path: Path | None = None,
    runtime_path: Path | None = None,
) -> dict[str, Any]:
    defaults = _load_toml(defaults_path or default_config_path())
    runtime = _load_toml(runtime_path or runtime_config_path())
    return _deep_merge(defaults, runtime)


def get_nested(data: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    cur: Any = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def runtime_value(dotted_key: str, default: Any = None) -> Any:
    return get_nested(load_runtime_config(), dotted_key, default)


def runtime_has_value(dotted_key: str) -> bool:
    marker = object()
    value = runtime_value(dotted_key, marker)
    if value is marker:
        return False
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def _set_nested(data: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cur = data
    for part in parts[:-1]:
        child = cur.get(part)
        if not isinstance(child, dict):
            child = {}
            cur[part] = child
        cur = child
    cur[parts[-1]] = value


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            lines.append(f"{section} = {_format_scalar(values)}")
            continue
        if lines:
            lines.append("")
        lines.append(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, dict):
                continue
            lines.append(f"{key} = {_format_scalar(value)}")
    return "\n".join(lines).rstrip() + "\n"


def set_runtime_config_value(dotted_key: str, value: Any, *, path: Path | None = None) -> None:
    config_path = path or runtime_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_toml(config_path)
    _set_nested(data, dotted_key, value)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp_path.write_text(_dump_toml(data), encoding="utf-8")
    tmp_path.replace(config_path)
