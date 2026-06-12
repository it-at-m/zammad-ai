# syntax=docker/dockerfile:1

FROM python:3.14.5-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./

RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev

COPY . .

EXPOSE 8081

CMD ["uv", "run", "python", "-m", "main"]
