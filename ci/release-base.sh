#!/usr/bin/env bash
# Коммит клиента, с которого копится выпуск: тег прошлого выпуска в ExileForge; нет тега - коммит `feat: release <прошлая версия>`; иначе
# HEAD~100. Печатает ревизию для диапазона <ревизия>..HEAD (ci/release_state.py: клиент и закреплённые в нём серверы).
# Использование: ci/release-base.sh <каталог клиента> <прошлый тег, например v0.24.2>
set -euo pipefail

src=$1
prev=$2
if git -C "$src" rev-parse -q --verify "refs/tags/$prev" >/dev/null; then
  echo "$prev"
elif base=$(git -C "$src" log --format=%H -1 --grep="^feat: release ${prev#v}$"); [ -n "$base" ]; then
  echo "$base"
else
  echo "HEAD~100"
fi
