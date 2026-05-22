"""Mapping helpers for Chat Completions <-> Responses payloads."""

from __future__ import annotations

from typing import Any


def chat_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map OpenAI chat messages to Responses API input format."""
    mapped: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            mapped.append(
                {
                    "role": role,
                    "content": [{"type": "input_text", "text": content}],
                }
            )
            continue
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    parts.append({"type": "input_text", "text": part.get("text", "")})
                elif ptype == "image_url":
                    image_url = part.get("image_url", {})
                    if isinstance(image_url, dict):
                        url = image_url.get("url", "")
                    else:
                        url = str(image_url or "")
                    if url:
                        parts.append({"type": "input_image", "image_url": {"url": url}})
            mapped.append({"role": role, "content": parts or [{"type": "input_text", "text": ""}]})
            continue
        mapped.append({"role": role, "content": [{"type": "input_text", "text": str(content)}]})
    return mapped


def responses_output_to_chat_message(response_obj: dict[str, Any]) -> dict[str, Any]:
    """Extract assistant message from a Responses API response."""
    output = response_obj.get("output", [])
    text = ""
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        parts = item.get("content", [])
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text += str(part.get("text", ""))
    return {"role": "assistant", "content": text}

