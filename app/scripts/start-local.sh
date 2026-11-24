#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
    echo 'Missing .env. Follow ../docs/RUN_AND_DEPLOY.md to initialize this machine; do not overwrite an existing database password.' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    if [[ $(id -u) -eq 0 ]] && command -v service >/dev/null; then service docker start; else
        echo 'Start Docker or run this script with Docker access.' >&2; exit 1
    fi
fi
docker compose config --quiet
docker compose up -d --no-build --wait --wait-timeout 180 db api web
docker compose ps
echo 'Open http://localhost:8080/ in your Windows browser.'
