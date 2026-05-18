#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OFPM_SRC="/mnt/d/OneDrive/0project/ofpm"
SHARED_DIR="/home/hyunsuk/shared"
OFFLINE_NETWORK="offline-internal-net"
ONLINE_NETWORK="online-bridge-net"

container_names=(
  online-ubuntu
  online-rocky
  online-centos7
  offline-ubuntu
  offline-rocky
  offline-centos7
)

ensure_networks() {
  docker network inspect "${OFFLINE_NETWORK}" >/dev/null 2>&1 || docker network create --internal "${OFFLINE_NETWORK}" >/dev/null
  docker network inspect "${ONLINE_NETWORK}" >/dev/null 2>&1 || docker network create "${ONLINE_NETWORK}" >/dev/null
}

ensure_images() {
  docker image inspect online:ubuntu24.04 >/dev/null 2>&1 || docker build -t online:ubuntu24.04 -f "${ROOT_DIR}/docker/online/Dockerfile.ubuntu24.04" "${ROOT_DIR}"
  docker image inspect online:rocky9.4 >/dev/null 2>&1 || docker build -t online:rocky9.4 -f "${ROOT_DIR}/docker/online/Dockerfile.rocky9.4" "${ROOT_DIR}"
  docker image inspect online:centos7 >/dev/null 2>&1 || docker build -t online:centos7 -f "${ROOT_DIR}/docker/online/Dockerfile.centos7" "${ROOT_DIR}"
  docker image inspect offline:ubuntu24.04 >/dev/null 2>&1 || docker build -t offline:ubuntu24.04 -f "${ROOT_DIR}/docker/offline/Dockerfile.ubuntu24.04" "${ROOT_DIR}"
  docker image inspect offline:rocky9.4 >/dev/null 2>&1 || docker build -t offline:rocky9.4 -f "${ROOT_DIR}/docker/offline/Dockerfile.rocky9.4" "${ROOT_DIR}"
  docker image inspect offline:centos7 >/dev/null 2>&1 || docker build -t offline:centos7 -f "${ROOT_DIR}/docker/offline/Dockerfile.centos7" "${ROOT_DIR}"
}

create_container() {
  local name="$1"
  local network="$2"
  local image="$3"
  if docker inspect "${name}" >/dev/null 2>&1; then
    return 0
  fi
  docker create \
    --name "${name}" \
    --network "${network}" \
    -v "${OFPM_SRC}:/home/hyunsuk/ofpm" \
    -v "${SHARED_DIR}:/home/hyunsuk/shared" \
    "${image}" >/dev/null
}

mkdir -p "${SHARED_DIR}"
ensure_networks
ensure_images

create_container online-ubuntu "${ONLINE_NETWORK}" online:ubuntu24.04
create_container online-rocky "${ONLINE_NETWORK}" online:rocky9.4
create_container online-centos7 "${ONLINE_NETWORK}" online:centos7
create_container offline-ubuntu "${OFFLINE_NETWORK}" offline:ubuntu24.04
create_container offline-rocky "${OFFLINE_NETWORK}" offline:rocky9.4
create_container offline-centos7 "${OFFLINE_NETWORK}" offline:centos7

echo "created dev containers (existing ones kept):"
docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}' | grep -E '^(online|offline)-'
