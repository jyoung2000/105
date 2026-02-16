#!/bin/bash
# Do NOT use set -e — chown may fail on restricted mounts and must not kill the container
PUID=${PUID:-99}
PGID=${PGID:-100}
echo "Starting with UID=$PUID, GID=$PGID"

# Adjust scraper user/group to match host UID/GID
groupmod -o -g "$PGID" scraper 2>/dev/null || true
usermod -o -u "$PUID" -g "$PGID" scraper 2>/dev/null || true

# Create data directories (volume mount may already exist)
mkdir -p /app/data/logs /app/data/config /app/data/temp /app/data/wallpapers /app/data/thumbnails

# Try chown but don't die if it fails (Unraid restricts ownership on mounts)
chown -R "$PUID:$PGID" /app/data 2>/dev/null || {
    echo "WARN: chown /app/data failed — trying chmod instead"
    chmod -R 777 /app/data 2>/dev/null || echo "WARN: chmod /app/data also failed — running as-is"
}

chown -R "$PUID:$PGID" /app/src 2>/dev/null || true
chown -R "$PUID:$PGID" /opt/playwright-browsers 2>/dev/null || true

# Copy model cache to scraper user home if needed
if [ -d /root/.cache/huggingface ] && [ ! -d /home/scraper/.cache/huggingface ]; then
    mkdir -p /home/scraper/.cache
    cp -r /root/.cache/huggingface /home/scraper/.cache/huggingface 2>/dev/null || true
    chown -R "$PUID:$PGID" /home/scraper/.cache 2>/dev/null || true
    echo "Model cache copied to scraper user"
fi

echo "Permissions fixed. Dropping to user scraper (UID=$PUID, GID=$PGID)..."
exec gosu scraper "$@"
