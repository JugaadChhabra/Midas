# Multi-stage build for a small runtime image.
FROM python:3.13-slim AS base

WORKDIR /app

# ffmpeg is used by app/keyframes.py for frame extraction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Local shorts cutter ML stack (CPU-only — see docs Phase A). Install torch from
# the CPU wheel index so the image doesn't pull ~2 GB of unused CUDA libs, then
# the remaining ML deps. ffmpeg is already installed above.
COPY requirements-ml.txt .
RUN pip install --no-cache-dir torch==2.12.1 torchvision==0.27.1 torchaudio==2.11.0 \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements-ml.txt

COPY app ./app

RUN mkdir -p /app/storage/keyframes

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5.0)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
