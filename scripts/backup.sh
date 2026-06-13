#!/bin/bash
# Daily backup: PostgreSQL dump + Redis snapshot
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="${POSTGRES_DB:-saas_db}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_HOST="${POSTGRES_HOST:-postgres}"
REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"
REDIS_CONTAINER="${REDIS_CONTAINER:-redis}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"

mkdir -p "$BACKUP_DIR"

# --- PostgreSQL ---
echo "[$(date)] Starting PostgreSQL backup..."
PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" pg_dump \
    -h "$DB_HOST" \
    -U "$DB_USER" \
    "$DB_NAME" \
    | gzip > "$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"
echo "[$(date)] PostgreSQL backup done: db_${TIMESTAMP}.sql.gz"

# --- Redis BGSAVE + copy RDB ---
echo "[$(date)] Triggering Redis BGSAVE..."
if [ -n "$REDIS_PASSWORD" ]; then
    REDIS_CLI_AUTH=(-a "$REDIS_PASSWORD")
else
    REDIS_CLI_AUTH=()
fi

redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "${REDIS_CLI_AUTH[@]}" BGSAVE

# Wait for BGSAVE to complete (poll up to 60s)
for i in $(seq 1 60); do
    SAVE_STATUS=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "${REDIS_CLI_AUTH[@]}" LASTSAVE)
    sleep 1
    NEW_STATUS=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "${REDIS_CLI_AUTH[@]}" LASTSAVE)
    if [ "$NEW_STATUS" != "$SAVE_STATUS" ]; then
        break
    fi
done

# Copy the RDB file from the Redis container
REDIS_RDB_PATH=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "${REDIS_CLI_AUTH[@]}" CONFIG GET dir | tail -1)
REDIS_RDB_FILE=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "${REDIS_CLI_AUTH[@]}" CONFIG GET dbfilename | tail -1)

if docker cp "${REDIS_CONTAINER}:${REDIS_RDB_PATH}/${REDIS_RDB_FILE}" \
        "$BACKUP_DIR/redis_${TIMESTAMP}.rdb" 2>/dev/null; then
    gzip "$BACKUP_DIR/redis_${TIMESTAMP}.rdb"
    echo "[$(date)] Redis backup done: redis_${TIMESTAMP}.rdb.gz"
else
    echo "[$(date)] WARNING: Could not copy Redis RDB (non-fatal)" >&2
fi

# --- Retention: remove backups older than RETAIN_DAYS ---
find "$BACKUP_DIR" -name "db_*.sql.gz"   -mtime +"$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name "redis_*.rdb.gz" -mtime +"$RETAIN_DAYS" -delete

echo "[$(date)] Backup complete. Retained last ${RETAIN_DAYS} days."
