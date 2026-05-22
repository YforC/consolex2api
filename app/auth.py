"""Authentication helpers for OpenAI-compatible endpoints."""

from __future__ import annotations

import hmac
from fastapi import Header, HTTPException, status

from .config import load_settings


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def verify_openai_api_key(
    authorization: str | None = Header(default=None),
) -> None:
    settings = load_settings()
    expected = settings.openai_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OPENAI_API_KEY is not configured on gateway server.",
        )
    provided = extract_bearer_token(authorization)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )


async def verify_admin_key(
    authorization: str | None = Header(default=None),
) -> None:
    settings = load_settings()
    expected = settings.admin_key.strip() or settings.openai_api_key.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_KEY or OPENAI_API_KEY is not configured on gateway server.",
        )
    provided = extract_bearer_token(authorization)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key.",
        )
