FROM python:3.12-slim

WORKDIR /app

COPY license_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY license_server /app/license_server

# SQLite DB persists in /data when a volume is mounted there.
ENV DATABASE_URL=sqlite:////data/licenses.db
RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" || exit 1

CMD ["uvicorn", "license_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
