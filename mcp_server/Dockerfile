FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /home/appuser/.cache/financial_mcp \
    && chown -R appuser:appuser /home/appuser/.cache

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

USER appuser
EXPOSE 8100

CMD ["python", "-m", "financial_mcp.server"]
