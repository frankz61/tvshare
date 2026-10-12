FROM python:3.12-slim

# Debian's ffmpeg includes libx264 and zscale (used to tone-map iPhone HDR videos).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV TVSHARE_DATA_DIR=/data \
    TVSHARE_PORT=8000 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

CMD ["python", "-m", "app.main"]
