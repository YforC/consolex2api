"""FastAPI entrypoint for OpenAI-compatible Grok gateway."""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .admin.routes import router as admin_router
from .errors import AppError, error_body
from .openai.routes import router as openai_router
from .upstream.xai_client import UpstreamError


app = FastAPI(
    title="ConsoleX OpenAI Gateway",
    version="0.1.0",
    description="OpenAI-compatible gateway backed by console.x.ai /v1/responses",
)
app.include_router(admin_router)
app.include_router(openai_router)


@app.middleware("http")
async def request_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    print(f"{request.method} {request.url.path} -> {response.status_code} ({elapsed_ms}ms)")
    return response


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(UpstreamError)
async def upstream_error_handler(_, exc: UpstreamError):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.details or str(exc), error_type="upstream_error"),
    )


@app.exception_handler(AppError)
async def app_error_handler(_, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=exc.body())


@app.exception_handler(HTTPException)
async def http_error_handler(_, exc: HTTPException):
    detail = exc.detail
    message = detail if isinstance(detail, str) else str(detail)
    error_type = "invalid_request_error" if exc.status_code < 500 else "server_error"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(message, error_type=error_type),
    )
