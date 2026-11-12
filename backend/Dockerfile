FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser
# Saved job results (a volume in docker-compose); owned by the app user.
RUN mkdir -p /data/job-results && chown appuser /data/job-results

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

USER appuser
EXPOSE 8000

CMD ["uvicorn", "stock_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
