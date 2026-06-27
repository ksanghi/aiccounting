# Books HQ cloud (web) image. Built from an ephemeral context that contains
# the engine (core/) + the web app (web/) — see web/deploy.sh. The repo-root
# .dockerignore excludes core/, which is why this build uses its own context.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY core /app/core
COPY web /app/web

ENV ACCGENIE_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
