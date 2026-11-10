#!/usr/bin/env bash
# Версия сервера из меток образа (org.opencontainers.image.version, её кладёт сборка образа): образ по неизменяемому дайджесту. Нужен вход в ghcr.io.
# Использование: ci/image-version.sh <образ> <sha256:дайджест>; в stdout - x.y.z
set -euo pipefail

[[ ${2:-} =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "::error::no image digest to read the version from" >&2; exit 1; }
docker buildx imagetools inspect "$1@$2" --format '{{json .}}' | python3 -I "$(dirname "$0")/test-stand.py" image-version
