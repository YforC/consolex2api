"""OpenAI-compatible routes for the custom Grok gateway."""

from __future__ import annotations

import asyncio
import json
import hmac
import time
from typing import Any, AsyncIterator

import websockets
from fastapi import APIRouter, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..adapters.chat_completions import (
    chat_messages_to_responses_input,
    responses_output_to_chat_message,
)
from ..adapters.responses import build_responses_payload
from ..adapters.sse import chat_error_stream, responses_async_stream_to_chat_stream
from ..auth import verify_openai_api_key
from ..config import Settings, load_settings, model_object
from ..auth import extract_bearer_token
from ..upstream.realtime import build_realtime_subprotocol, build_realtime_ws_url, prepare_realtime_client_message
from ..upstream.xai_client import (
    UpstreamError,
    create_realtime_client_secret,
    create_response_json,
    stream_response_events,
)


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


def _reasoning_from_effort(effort: str | None) -> dict[str, Any] | None:
    value = str(effort or "").strip()
    return {"effort": value} if value else None


def _responses_request_payload(req: ResponsesRequest, settings: Settings) -> dict[str, Any]:
    is_stream = bool(req.stream)
    return build_responses_payload(
        model=req.model,
        input_val=req.input,
        instructions=req.instructions,
        stream=is_stream,
        temperature=req.temperature if req.temperature is not None else settings.default_temperature,
        top_p=req.top_p if req.top_p is not None else settings.default_top_p,
        max_output_tokens=req.max_output_tokens,
        tools=req.tools,
        tool_choice=req.tool_choice,
        reasoning=req.reasoning
        if req.reasoning is not None
        else _reasoning_from_effort(settings.default_reasoning_effort),
        include=req.include,
        store=req.store,
        tools_enabled=settings.tools_enabled,
    )


def _chat_request_payload(req: ChatCompletionRequest, settings: Settings) -> dict[str, Any]:
    is_stream = bool(req.stream)
    response_input = chat_messages_to_responses_input(req.messages)
    reasoning_effort = req.reasoning_effort or settings.default_reasoning_effort
    return build_responses_payload(
        model=req.model,
        input_val=response_input,
        instructions=None,
        stream=is_stream,
        temperature=req.temperature if req.temperature is not None else settings.default_temperature,
        top_p=req.top_p if req.top_p is not None else settings.default_top_p,
        max_output_tokens=req.max_tokens,
        tools=req.tools,
        tool_choice=req.tool_choice,
        reasoning=_reasoning_from_effort(reasoning_effort),
        tools_enabled=settings.tools_enabled,
    )


@router.get("/models", dependencies=[Depends(verify_openai_api_key)])
async def list_models() -> JSONResponse:
    settings = load_settings()
    data = [model_object(mid) for mid in settings.model_list]
    return JSONResponse({"object": "list", "data": data})


@router.post("/realtime/client_secrets", dependencies=[Depends(verify_openai_api_key)])
async def realtime_client_secrets(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    settings = load_settings()
    if not settings.has_upstream_auth():
        raise HTTPException(status_code=500, detail="UPSTREAM_COOKIE or UPSTREAM_SSO is required.")
    return JSONResponse(await create_realtime_client_secret(settings, payload or {}))


def _websocket_api_key(websocket: WebSocket) -> str:
    auth = websocket.headers.get("authorization")
    token = extract_bearer_token(auth)
    if token:
        return token
    return websocket.query_params.get("api_key", "")


def _xai_realtime_subprotocol(raw_header: str | None) -> str:
    for part in str(raw_header or "").split(","):
        protocol = part.strip()
        if protocol.startswith("xai-client-secret."):
            return protocol
    return ""


async def _accept_or_close_realtime(websocket: WebSocket) -> bool:
    settings = load_settings()
    expected = settings.openai_api_key
    provided = _websocket_api_key(websocket)
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        await websocket.close(code=1008)
        return False
    return True


@router.websocket("/realtime")
async def realtime_websocket(websocket: WebSocket) -> None:
    if not await _accept_or_close_realtime(websocket):
        return
    settings = load_settings()
    model = websocket.query_params.get("model", "grok-voice-think-fast-1.0")
    client_protocol = _xai_realtime_subprotocol(websocket.headers.get("sec-websocket-protocol"))
    downstream_protocol = client_protocol or None
    await websocket.accept(subprotocol=downstream_protocol)

    upstream_protocol = client_protocol
    if not upstream_protocol:
        secret = await create_realtime_client_secret(settings, {"expires_after": {"seconds": 300}})
        upstream_protocol = build_realtime_subprotocol(str(secret.get("value", "")))
    if not upstream_protocol:
        await websocket.close(code=1011)
        return

    headers = {
        "Origin": settings.upstream_origin,
        "User-Agent": settings.upstream_user_agent,
    }
    upstream_url = build_realtime_ws_url(model)

    try:
        async with websockets.connect(
            upstream_url,
            additional_headers=headers,
            subprotocols=[upstream_protocol],
            ping_interval=None,
        ) as upstream:
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if "text" in message:
                        await upstream.send(prepare_realtime_client_message(message["text"]))
                    elif "bytes" in message:
                        await upstream.send(prepare_realtime_client_message(message["bytes"]))
                    elif message.get("type") == "websocket.disconnect":
                        await upstream.close()
                        return

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(str(message))

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass


@router.post("/responses", dependencies=[Depends(verify_openai_api_key)])
async def responses_create(req: ResponsesRequest):
    settings = load_settings()
    if not settings.has_upstream_auth():
        raise HTTPException(status_code=500, detail="UPSTREAM_COOKIE or UPSTREAM_SSO is required.")

    is_stream = bool(req.stream)
    payload = _responses_request_payload(req, settings)
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
    payload = _chat_request_payload(req, settings)

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
