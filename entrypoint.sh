#!/bin/bash
# Do NOT use set -e — chown/chmod may fail on restricted mounts and must not kill the container
PUID=${PUID:-99}
PGID=${PGID:-100}
echo "Starting with UID=$PUID, GID=$PGID"

# Adjust scraper user/group to match host UID/GID
groupmod -o -g "$PGID" scraper 2>/dev/null || true
usermod -o -u "$PUID" -g "$PGID" scraper 2>/dev/null || true

# Create data directories (volume mount may already exist)
# mkdir -p will succeed if dirs already exist even without write perms on parent
mkdir -p /app/data/logs /app/data/config /app/data/temp /app/data/wallpapers /app/data/thumbnails 2>/dev/null || true

# Try to fix permissions — multiple strategies for Unraid compatibility
# Strategy 1: chown the whole tree
if chown -R "$PUID:$PGID" /app/data 2>/dev/null; then
    echo "Permissions set via chown"
# Strategy 2: chmod to world-writable
elif chmod -R 777 /app/data 2>/dev/null; then
    echo "Permissions set via chmod 777"
# Strategy 3: try each subdirectory individually
else
    echo "WARN: Bulk permission fix failed — trying individual directories"
    for dir in logs config temp wallpapers thumbnails; do
        chown -R "$PUID:$PGID" "/app/data/$dir" 2>/dev/null || \
        chmod -R 777 "/app/data/$dir" 2>/dev/null || \
        echo "WARN: Could not fix permissions on /app/data/$dir — continuing anyway"
    done
fi

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
