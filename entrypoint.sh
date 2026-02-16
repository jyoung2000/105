#!/bin/bash
set -e
PUID=${PUID:-99}
PGID=${PGID:-100}
echo "Starting with UID=$PUID, GID=$PGID"
groupmod -o -g "$PGID" scraper 2>/dev/null || true
usermod -o -u "$PUID" -g "$PGID" scraper 2>/dev/null || true
mkdir -p /app/data/logs /app/data/config /app/data/temp /app/data/wallpapers /app/data/thumbnails
chown -R scraper:scraper /app/data
chown -R scraper:scraper /app/src 2>/dev/null || true
chown -R scraper:scraper /opt/playwright-browsers 2>/dev/null || true
if [ -d /root/.cache/huggingface ] && [ ! -d /home/scraper/.cache/huggingface ]; then
    mkdir -p /home/scraper/.cache
    cp -r /root/.cache/huggingface /home/scraper/.cache/huggingface
    chown -R scraper:scraper /home/scraper/.cache
    echo "Model cache copied to scraper user"
fi
echo "Permissions fixed. Dropping to user scraper (UID=$PUID, GID=$PGID)..."
exec gosu scraper "$@"
