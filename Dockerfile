FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn curl_cffi pydantic

COPY gateway ./gateway

EXPOSE 8787

CMD ["python", "-m", "uvicorn", "gateway.app.main:app", "--host", "0.0.0.0", "--port", "8787"]
