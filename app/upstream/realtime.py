"""Helpers for x.ai Realtime websocket proxying."""

from __future__ import annotations

from urllib.parse import urlencode

REALTIME_WS_BASE = "wss://api.x.ai/v1/realtime"
REALTIME_CLIENT_SECRET_URL = "https://console.x.ai/v1/realtime/client_secrets"


def build_realtime_ws_url(model: str) -> str:
    model_id = (model or "grok-voice-think-fast-1.0").strip() or "grok-voice-think-fast-1.0"
    return f"{REALTIME_WS_BASE}?{urlencode({'model': model_id})}"


def build_realtime_subprotocol(secret_value: str) -> str:
    value = str(secret_value or "").strip()
    if not value:
        return ""
    if value.startswith("xai-client-secret."):
        return value
    return f"xai-client-secret.{value}"


def prepare_realtime_client_message(message: str | bytes) -> str | bytes:
    """Return client websocket messages unchanged.

    Stop/reset semantics live in x.ai's Realtime protocol. The gateway should
    not transform frames like ``response.cancel`` or ``session.update``.
    """

    return message


__all__ = [
    "REALTIME_CLIENT_SECRET_URL",
    "REALTIME_WS_BASE",
    "build_realtime_subprotocol",
    "build_realtime_ws_url",
    "prepare_realtime_client_message",
]
