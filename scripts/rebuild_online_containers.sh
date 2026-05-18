#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OFPM_SRC="/mnt/d/OneDrive/0project/ofpm"
SHARED_DIR="/home/hyunsuk/shared"
NETWORK_NAME="online-bridge-net"

containers=(
  online-ubuntu
  online-rocky
  online-centos7
)

images=(
  online:ubuntu24.04
  online:rocky9.4
  online:centos7
  centos:7
)

for container in "${containers[@]}"; do
  docker rm -f "${container}" >/dev/null 2>&1 || true
done

for image in "${images[@]}"; do
  docker rmi -f "${image}" >/dev/null 2>&1 || true
done

docker network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
docker network create "${NETWORK_NAME}" >/dev/null

mkdir -p "${SHARED_DIR}"

docker build -t online:ubuntu24.04 -f "${ROOT_DIR}/docker/online/Dockerfile.ubuntu24.04" "${ROOT_DIR}"
docker build -t online:rocky9.4 -f "${ROOT_DIR}/docker/online/Dockerfile.rocky9.4" "${ROOT_DIR}"
docker build -t online:centos7 -f "${ROOT_DIR}/docker/online/Dockerfile.centos7" "${ROOT_DIR}"

docker run -d \
  --name online-ubuntu \
  --network "${NETWORK_NAME}" \
  -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
  -v "${SHARED_DIR}:/home/hyunsuk/shared" \
  online:ubuntu24.04 >/dev/null

docker run -d \
  --name online-rocky \
  --network "${NETWORK_NAME}" \
  -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
  -v "${SHARED_DIR}:/home/hyunsuk/shared" \
  online:rocky9.4 >/dev/null

docker run -d \
  --name online-centos7 \
  --network "${NETWORK_NAME}" \
  -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
  -v "${SHARED_DIR}:/home/hyunsuk/shared" \
  online:centos7 >/dev/null

echo "rebuilt online containers:"
docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep '^online-'
