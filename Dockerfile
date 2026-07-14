# Multi-stage build for a small runtime image.
FROM python:3.13-slim AS base

WORKDIR /app

# ffmpeg is used by app/keyframes.py for frame extraction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Deno: the JS runtime yt-dlp's EJS solver REQUIRES to solve YouTube's "n"
# signature challenge. Without it yt-dlp returns no formats ("This video is not
# available") even with a valid PO token — the failure that broke shorts on the
# box. node is NOT accepted (yt-dlp reports "node (unsupported)"); Deno is, and
# verified good with yt-dlp==2026.6.9 (log: "[jsc:deno] Solving JS challenges").
# Pinned for reproducibility; fetched+unzipped via the image's own python so we
# don't add curl/unzip. ytdlp_options() already lists deno first in js_runtimes.
ARG DENO_VERSION=2.9.2
RUN DENO_VERSION="${DENO_VERSION}" python -c "import urllib.request,zipfile,io,os; \
v=os.environ['DENO_VERSION']; \
url=f'https://github.com/denoland/deno/releases/download/v{v}/deno-x86_64-unknown-linux-gnu.zip'; \
zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url).read())).extractall('/usr/local/bin'); \
os.chmod('/usr/local/bin/deno', 0o755)" \
 && /usr/local/bin/deno --version

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

RUN mkdir -p /app/storage/keyframes /app/shorts_cache /app/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5.0)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
