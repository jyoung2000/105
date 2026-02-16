FROM python:3.12-slim AS builder
WORKDIR /app

# Step 1: CPU-only torch into STANDARD location — pip will see it's installed
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Step 2: requirements.txt — pip sees torch is already satisfied, won't re-download CUDA version
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 libasound2 \
    libxshmfence1 libx11-xcb1 libjpeg62-turbo libwebp7 libpng16-16 \
    fonts-liberation gosu && rm -rf /var/lib/apt/lists/*

# Copy from standard locations — NOT /install
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . .
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN mkdir -p /opt/playwright-browsers && playwright install --with-deps chromium
RUN python scripts/download_model.py
RUN groupadd -g 1000 scraper && useradd -u 1000 -g scraper -m -s /bin/bash scraper
RUN chmod +x /app/entrypoint.sh
EXPOSE 1629
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:1629/api/health')" || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "1629", "--workers", "1"]
