# ECS Desk on Cloud Run.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip check

COPY desk_server.py desk.html ./
COPY ecs_desk/ ./ecs_desk/

# Cloud Run sets PORT and may change it, so it is read at start, not baked in.
ENV PORT=8080
CMD exec uvicorn desk_server:app --host 0.0.0.0 --port ${PORT}
