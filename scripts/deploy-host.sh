#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${ROOT_DIR}/backend/.env" ]]; then
  echo "Missing backend/.env. Create it from backend/.env.example first."
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/.env.host" ]]; then
  echo "Missing .env.host. Create it from .env.host.example and set DOMAIN."
  exit 1
fi

cd "${ROOT_DIR}"
docker compose --env-file .env.host -f docker-compose.host.yml up -d --build

echo "Deployment started."
echo "Check status with: docker compose --env-file .env.host -f docker-compose.host.yml ps"
