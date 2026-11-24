#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
backup_file="${1:?提供备份文件路径}"
# Restore into a separate verification database, never over the live database.
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" adc_restore_check'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d adc_restore_check --no-owner --exit-on-error' < "$backup_file"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d adc_restore_check -c "SELECT count(*) AS tables FROM information_schema.tables WHERE table_schema= '\''public'\'' AND table_type='\''BASE TABLE'\'';"'
