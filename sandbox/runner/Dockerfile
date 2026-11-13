# Sandbox Runner (SCRUM-70): the only service that mounts the Docker socket.
FROM docker:28-cli AS docker-cli

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY sandbox_runner ./sandbox_runner

EXPOSE 8200
CMD ["uvicorn", "sandbox_runner.app:app", "--host", "0.0.0.0", "--port", "8200"]
