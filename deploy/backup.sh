#!/usr/bin/env bash
# PostgreSQL 备份：pg_dump 压缩后落到 backups/，自动保留最近 30 份。
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE="${COMPOSE_FILE:-docker-compose.prod.yml}"
if [ ! -f "$ENV_FILE" ]; then
  echo "错误：未找到 $SCRIPT_DIR/$ENV_FILE，请先配置生产环境变量。" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
KEEP="${BACKUP_KEEP:-30}"
mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y%m%d-%H%M%S)
FNAME="$BACKUP_DIR/procurement-$STAMP.sql.gz"

# 显式指定生产 Compose，避免在项目根目录误用开发 Compose。
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-procurement}" "${POSTGRES_DB:-procurement}" \
  | gzip > "$FNAME"

echo "备份完成：$FNAME"
# 只保留最近 KEEP 份
ls -1t "$BACKUP_DIR"/procurement-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "当前备份数：$(ls -1 "$BACKUP_DIR"/procurement-*.sql.gz 2>/dev/null | wc -l | tr -d ' ')"
