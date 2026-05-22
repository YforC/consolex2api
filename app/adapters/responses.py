"""Mapping helpers for Responses API passthrough."""

from __future__ import annotations

from typing import Any


DEFAULT_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search", "enable_image_understanding": True},
    {"type": "x_search", "enable_video_understanding": True},
]

DEFAULT_INCLUDE = ["reasoning.encrypted_content"]


def _tool_enabled(tool: dict[str, Any], *, web_search_enabled: bool, x_search_enabled: bool) -> bool:
    tool_type = tool.get("type")
    if tool_type == "web_search":
        return web_search_enabled
    if tool_type == "x_search":
        return x_search_enabled
    return True


def _default_tools(*, web_search_enabled: bool, x_search_enabled: bool) -> list[dict[str, Any]]:
    return [
        tool
        for tool in DEFAULT_TOOLS
        if _tool_enabled(tool, web_search_enabled=web_search_enabled, x_search_enabled=x_search_enabled)
    ]


def _filtered_tools(
    tools: list[Any] | None,
    *,
    web_search_enabled: bool,
    x_search_enabled: bool,
) -> list[Any]:
    if tools is None:
        return _default_tools(web_search_enabled=web_search_enabled, x_search_enabled=x_search_enabled)
    filtered: list[Any] = []
    changed = False
    for tool in tools:
        if not isinstance(tool, dict):
            filtered.append(tool)
            continue
        if _tool_enabled(tool, web_search_enabled=web_search_enabled, x_search_enabled=x_search_enabled):
            filtered.append(tool)
        else:
            changed = True
    if not changed and len(filtered) == len(tools):
        return tools
    return filtered


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
    tools_enabled: bool = True,
    web_search_enabled: bool = True,
    x_search_enabled: bool = True,
) -> dict[str, Any]:
    if tools_enabled:
        payload_tools = _filtered_tools(
            tools,
            web_search_enabled=web_search_enabled,
            x_search_enabled=x_search_enabled,
        )
        if payload_tools:
            payload_tool_choice = "auto" if tool_choice is None else tool_choice
        else:
            payload_tool_choice = "none"
    else:
        payload_tools = []
        payload_tool_choice = "none"

    payload: dict[str, Any] = {
        "model": model,
        "input": input_val,
        "stream": stream,
        "store": False if store is None else store,
        "include": DEFAULT_INCLUDE if include is None else include,
        "tools": payload_tools,
        "tool_choice": payload_tool_choice,
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
