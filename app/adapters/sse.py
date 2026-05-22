"""SSE conversion helpers."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterable, AsyncIterator, Iterable, Iterator

from ..errors import error_body


def _chat_chunk(
    *,
    completion_id: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def chat_error_stream(message: str, *, model: str) -> Iterator[str]:
    yield from sse_error_stream(message, error_type="upstream_error")


def sse_error_stream(
    message: str,
    *,
    error_type: str = "server_error",
    code: str | None = None,
    param: str | None = None,
) -> Iterator[str]:
    yield "event: error\n"
    yield f"data: {json.dumps(error_body(message, error_type=error_type, code=code, param=param), ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _text_from_output_item(item: dict[str, Any]) -> str:
    if item.get("type") != "message":
        return ""
    parts: list[str] = []
    content = item.get("content") or []
    if not isinstance(content, list):
        return ""
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"output_text", "text"}:
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _text_from_response(response: dict[str, Any]) -> str:
    parts: list[str] = []
    output = response.get("output") or []
    if not isinstance(output, list):
        return ""
    for item in output:
        if isinstance(item, dict):
            parts.append(_text_from_output_item(item))
    return "".join(parts)


def responses_stream_to_chat_stream(
    upstream_lines: Iterable[str],
    *,
    model: str,
) -> Iterator[str]:
    """Convert Responses SSE events into Chat Completions SSE chunks."""
    event_name = ""
    completion_id = "chatcmpl-proxy"
    current_model = model
    done = False
    emitted_text = False

    for raw in upstream_lines:
        line = (raw or "").strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:") :].strip()
        if data_str == "[DONE]":
            if not done:
                done = True
                yield "data: [DONE]\n\n"
            continue
        try:
            obj = json.loads(data_str)
        except ValueError:
            continue

        if event_name == "response.created":
            response = obj.get("response", {})
            completion_id = response.get("id", completion_id)
            current_model = response.get("model", current_model)
            # First chunk should include role for better SDK compatibility.
            yield _chat_chunk(
                completion_id=completion_id,
                model=current_model,
                delta={"role": "assistant"},
            )
            continue

        if event_name == "response.output_text.delta":
            delta_text = str(obj.get("delta", ""))
            if delta_text:
                emitted_text = True
                yield _chat_chunk(
                    completion_id=completion_id,
                    model=current_model,
                    delta={"content": delta_text},
                )
            continue

        if event_name == "response.output_item.done":
            item_text = _text_from_output_item(obj.get("item", {}))
            if item_text and not emitted_text:
                emitted_text = True
                yield _chat_chunk(
                    completion_id=completion_id,
                    model=current_model,
                    delta={"content": item_text},
                )
            continue

        if event_name == "response.completed":
            response = obj.get("response", {})
            completion_id = response.get("id", completion_id)
            current_model = response.get("model", current_model)
            final_text = _text_from_response(response)
            if final_text and not emitted_text:
                emitted_text = True
                yield _chat_chunk(
                    completion_id=completion_id,
                    model=current_model,
                    delta={"content": final_text},
                )
            yield _chat_chunk(
                completion_id=completion_id,
                model=current_model,
                delta={},
                finish_reason="stop",
            )
            if not done:
                done = True
                yield "data: [DONE]\n\n"
            continue

        if event_name == "error":
            err_msg = "Upstream stream error"
            if isinstance(obj, dict):
                err_msg = str(obj.get("message") or obj.get("error") or err_msg)
            error_payload = {
                "error": {"message": err_msg, "type": "server_error"},
            }
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            if not done:
                done = True
                yield "data: [DONE]\n\n"
            continue

    if not done:
        yield _chat_chunk(
            completion_id=completion_id,
            model=current_model,
            delta={},
            finish_reason="stop",
        )
        yield "data: [DONE]\n\n"


async def responses_async_stream_to_chat_stream(
    upstream_lines: AsyncIterable[str],
    *,
    model: str,
) -> AsyncIterator[str]:
    # Reuse the sync logic by buffering small line batches.
    event_name = ""
    completion_id = "chatcmpl-proxy"
    current_model = model
    done = False
    emitted_text = False

    async for raw in upstream_lines:
        line = (raw or "").strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:") :].strip()
        if data_str == "[DONE]":
            if not done:
                done = True
                yield "data: [DONE]\n\n"
            continue
        try:
            obj = json.loads(data_str)
        except ValueError:
            continue

        if event_name == "response.created":
            response = obj.get("response", {})
            completion_id = response.get("id", completion_id)
            current_model = response.get("model", current_model)
            yield _chat_chunk(
                completion_id=completion_id,
                model=current_model,
                delta={"role": "assistant"},
            )
            continue

        if event_name == "response.output_text.delta":
            delta_text = str(obj.get("delta", ""))
            if delta_text:
                emitted_text = True
                yield _chat_chunk(
                    completion_id=completion_id,
                    model=current_model,
                    delta={"content": delta_text},
                )
            continue

        if event_name == "response.output_item.done":
            item_text = _text_from_output_item(obj.get("item", {}))
            if item_text and not emitted_text:
                emitted_text = True
                yield _chat_chunk(
                    completion_id=completion_id,
                    model=current_model,
                    delta={"content": item_text},
                )
            continue

        if event_name == "response.completed":
            response = obj.get("response", {})
            completion_id = response.get("id", completion_id)
            current_model = response.get("model", current_model)
            final_text = _text_from_response(response)
            if final_text and not emitted_text:
                emitted_text = True
                yield _chat_chunk(
                    completion_id=completion_id,
                    model=current_model,
                    delta={"content": final_text},
                )
            yield _chat_chunk(
                completion_id=completion_id,
                model=current_model,
                delta={},
                finish_reason="stop",
            )
            if not done:
                done = True
                yield "data: [DONE]\n\n"
            continue

        if event_name == "error":
            err_msg = "Upstream stream error"
            if isinstance(obj, dict):
                err_msg = str(obj.get("message") or obj.get("error") or err_msg)
            error_payload = {
                "error": {"message": err_msg, "type": "server_error"},
            }
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            if not done:
                done = True
                yield "data: [DONE]\n\n"
            continue

    if not done:
        yield _chat_chunk(
            completion_id=completion_id,
            model=current_model,
            delta={},
            finish_reason="stop",
        )
        yield "data: [DONE]\n\n"
