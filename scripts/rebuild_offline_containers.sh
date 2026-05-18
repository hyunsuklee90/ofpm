#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OFPM_SRC="/mnt/d/OneDrive/0project/ofpm"
SHARED_DIR="/home/hyunsuk/shared"
NETWORK_NAME="offline-internal-net"

containers=(
  offline-ubuntu
  offline-rocky
  offline-centos7
)

images=(
  offline:ubuntu24.04
  offline:rocky9.4
  offline:centos7
  pi-offline-test:ubuntu
  pi-offline-test:rocky-9.4
  centos:7
)

for container in "${containers[@]}"; do
  docker rm -f "${container}" >/dev/null 2>&1 || true
done

for image in "${images[@]}"; do
  docker rmi -f "${image}" >/dev/null 2>&1 || true
done

docker network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
docker network create --internal "${NETWORK_NAME}" >/dev/null

mkdir -p "${SHARED_DIR}"

docker build -t offline:ubuntu24.04 -f "${ROOT_DIR}/docker/offline/Dockerfile.ubuntu24.04" "${ROOT_DIR}"
docker build -t offline:rocky9.4 -f "${ROOT_DIR}/docker/offline/Dockerfile.rocky9.4" "${ROOT_DIR}"
docker build -t offline:centos7 -f "${ROOT_DIR}/docker/offline/Dockerfile.centos7" "${ROOT_DIR}"

docker run -d \
  --name offline-ubuntu \
  --network "${NETWORK_NAME}" \
  -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
  -v "${SHARED_DIR}:/home/hyunsuk/shared" \
  offline:ubuntu24.04 >/dev/null

docker run -d \
  --name offline-rocky \
  --network "${NETWORK_NAME}" \
  -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
  -v "${SHARED_DIR}:/home/hyunsuk/shared" \
  offline:rocky9.4 >/dev/null

docker run -d \
  --name offline-centos7 \
  --network "${NETWORK_NAME}" \
  -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
  -v "${SHARED_DIR}:/home/hyunsuk/shared" \
  offline:centos7 >/dev/null

echo "rebuilt offline containers:"
docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep '^offline-'
