"""Mapping helpers for Responses API passthrough."""

from __future__ import annotations

from typing import Any


DEFAULT_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search", "enable_image_understanding": True},
    {"type": "x_search", "enable_video_understanding": True},
]

DEFAULT_INCLUDE = ["reasoning.encrypted_content"]


def build_responses_payload(
    *,
    model: str,
    input_val: str | list[Any],
    instructions: str | None,
    stream: bool,
    temperature: float | None,
    top_p: float | None,
    max_output_tokens: int | None,
    tools: list[Any] | None,
    tool_choice: Any,
    reasoning: dict[str, Any] | None = None,
    include: list[str] | None = None,
    store: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": input_val,
        "stream": stream,
        "store": False if store is None else store,
        "include": DEFAULT_INCLUDE if include is None else include,
        "tools": DEFAULT_TOOLS if tools is None else tools,
        "tool_choice": "auto" if tool_choice is None else tool_choice,
    }
    if instructions is not None:
        payload["instructions"] = instructions
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    payload["max_output_tokens"] = max_output_tokens if max_output_tokens is not None else 1000000
    if reasoning is not None:
        payload["reasoning"] = reasoning
    return payload
