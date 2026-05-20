#!/usr/bin/env bash
set -euo pipefail

containers=("$@")
if [ "${#containers[@]}" -eq 0 ]; then
  containers=(
    online-ubuntu
    online-rocky
    online-centos7
    offline-ubuntu
    offline-rocky
    offline-centos7
  )
fi

for container in "${containers[@]}"; do
  if docker inspect "${container}" >/dev/null 2>&1; then
    docker stop "${container}" >/dev/null || true
  fi
done

echo "stopped containers:"
docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}' | grep -E '^(online|offline)-'
