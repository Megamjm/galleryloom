FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/galleryloom

RUN apt-get update && apt-get install -y --no-install-recommends \
    zip unzip p7zip-full unrar-free curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY ui ./ui

# create runtime dirs (will be mounted in Unraid)
RUN mkdir -p /config /data /output /duplicates

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 CMD curl -f http://localhost:8080/api/health || exit 1

CMD ["bash", "-lc", "python scripts/init_db.py && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
