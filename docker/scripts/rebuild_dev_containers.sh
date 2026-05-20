#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

bash "${ROOT_DIR}/docker/scripts/rebuild_online_containers.sh"
bash "${ROOT_DIR}/docker/scripts/rebuild_offline_containers.sh"

echo
echo "rebuilt all dev containers:"
docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}' | grep -E '^(online|offline)-'
