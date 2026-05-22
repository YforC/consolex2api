FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn curl_cffi pydantic websockets

COPY . .

EXPOSE 8787

CMD ["python", "-m", "app"]

