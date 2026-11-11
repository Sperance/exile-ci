#!/usr/bin/env bash
# Версия и номер тестовой сборки клиента (x.y.z_test, #1084): последний боевой тег v<x.y.z> + k patch, прошлая версия - из qa-latest, повтор той же сборки - из её
# предрелиза qa-<число коммитов> (ci/qa-files.py version). Одна логика для client.yml (шаг «Test build target») и check-wip.yml (сухой прогон, ничего не пишет).
# Использование: ci/qa-version.sh <клон клиента с историей коммитов> <sha клиента> <файл выхода>; в файл: name=<версия>, code=<число коммитов>.
# Окружение: GH_TOKEN, GITHUB_REPOSITORY (релизы этого репозитория читаются). Нет выпущенной версии - код 1.
set -euo pipefail

here=$(dirname "${BASH_SOURCE[0]}")
. "$here/retry.sh"

clone=$1
sha=$2
out=$3
code=$(git -C "$clone" rev-list --count "$sha")
last=$(netcall read gh release list -R "$GITHUB_REPOSITORY" --limit 300 --json tagName --jq '.[].tagName' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true)
[ -n "$last" ] || { echo "::error::no released version to number the test build from"; exit 1; }
previous=$(netcall read gh release download qa-latest -R "$GITHUB_REPOSITORY" -p update.json -O - 2>/dev/null | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["versionName"])' 2>/dev/null || true)
same=$(netcall read gh release view "qa-$code" -R "$GITHUB_REPOSITORY" --json body --jq .body 2>/dev/null | sed -n 's/^Test build \([^ ]*\) .*/\1/p' | head -1 || true)
python3 -I "$here/qa-files.py" version "$last" "$code" "${sha:0:7}" "${previous:--}" "${same:--}" "$out"
echo "code=$code" >> "$out"
