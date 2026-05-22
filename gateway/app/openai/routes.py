"""OpenAI-compatible routes for the custom Grok gateway."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..adapters.chat_completions import (
    chat_messages_to_responses_input,
    responses_output_to_chat_message,
)
from ..adapters.responses import build_responses_payload
from ..adapters.sse import chat_error_stream, responses_async_stream_to_chat_stream
from ..auth import verify_openai_api_key
from ..config import load_settings, model_object
from ..upstream.xai_client import UpstreamError, create_response_json, stream_response_events


router = APIRouter(prefix="/v1")
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[dict[str, Any]]
    stream: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    tools: list[Any] | None = None
    tool_choice: Any = None
    reasoning_effort: str | None = None
    stream_options: dict[str, Any] | None = None


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    input: str | list[Any]
    instructions: str | None = None
    stream: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: list[Any] | None = None
    tool_choice: Any = None
    reasoning: dict[str, Any] | None = None
    include: list[str] | None = None
    store: bool | None = None


@router.get("/models", dependencies=[Depends(verify_openai_api_key)])
async def list_models() -> JSONResponse:
    settings = load_settings()
    data = [model_object(mid) for mid in settings.model_list]
    return JSONResponse({"object": "list", "data": data})


@router.post("/responses", dependencies=[Depends(verify_openai_api_key)])
async def responses_create(req: ResponsesRequest):
    settings = load_settings()
    if not settings.has_upstream_auth():
        raise HTTPException(status_code=500, detail="UPSTREAM_COOKIE or UPSTREAM_SSO is required.")

    is_stream = bool(req.stream)
    payload = build_responses_payload(
        model=req.model,
        input_val=req.input,
        instructions=req.instructions,
        stream=is_stream,
        temperature=req.temperature if req.temperature is not None else settings.default_temperature,
        top_p=req.top_p if req.top_p is not None else settings.default_top_p,
        max_output_tokens=req.max_output_tokens,
        tools=req.tools,
        tool_choice=req.tool_choice,
        reasoning=req.reasoning,
        include=req.include,
        store=req.store,
    )
    if not is_stream:
        try:
            data = await create_response_json(settings, payload)
        except UpstreamError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.details or str(exc)) from exc
        return JSONResponse(data)

    async def _stream() -> AsyncIterator[str]:
        try:
            async for line in stream_response_events(settings, payload):
                if not line:
                    continue
                yield f"{line}\n"
        except UpstreamError as exc:
            for chunk in chat_error_stream(exc.details or str(exc), model=req.model):
                yield chunk

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/chat/completions", dependencies=[Depends(verify_openai_api_key)])
async def chat_completions(req: ChatCompletionRequest):
    settings = load_settings()
    if not settings.has_upstream_auth():
        raise HTTPException(status_code=500, detail="UPSTREAM_COOKIE or UPSTREAM_SSO is required.")

    is_stream = bool(req.stream)
    response_input = chat_messages_to_responses_input(req.messages)
    payload = build_responses_payload(
        model=req.model,
        input_val=response_input,
        instructions=None,
        stream=is_stream,
        temperature=req.temperature if req.temperature is not None else settings.default_temperature,
        top_p=req.top_p if req.top_p is not None else settings.default_top_p,
        max_output_tokens=req.max_tokens,
        tools=req.tools,
        tool_choice=req.tool_choice,
        reasoning={"effort": req.reasoning_effort} if req.reasoning_effort else None,
    )

    if not is_stream:
        try:
            upstream = await create_response_json(settings, payload)
        except UpstreamError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.details or str(exc)) from exc

        response_obj = upstream.get("response", upstream)
        message = responses_output_to_chat_message(response_obj)
        usage = response_obj.get("usage") or {}
        out = {
            "id": response_obj.get("id", "chatcmpl-proxy"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_obj.get("model", req.model),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(usage.get("input_tokens", 0) or 0),
                "completion_tokens": int(usage.get("output_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
        }
        return JSONResponse(out)

    async def _stream() -> AsyncIterator[str]:
        try:
            async for chunk in responses_async_stream_to_chat_stream(
                stream_response_events(settings, payload),
                model=req.model,
            ):
                yield chunk
        except UpstreamError as exc:
            for chunk in chat_error_stream(exc.details or str(exc), model=req.model):
                yield chunk

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
