# Image for one sandboxed analysis run (SCRUM-69). It has no network tools and runs as a
# non-root user; the runner adds every other limit when it starts the container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    MPLBACKEND=Agg \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

COPY requirements.txt /opt/sandbox/requirements.txt
RUN pip install -r /opt/sandbox/requirements.txt \
    && rm -rf /root/.cache \
    && useradd --uid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin sandbox \
    && mkdir -p /input && chown sandbox /input

COPY harness.py /opt/sandbox/harness.py

USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/opt/sandbox/harness.py"]
