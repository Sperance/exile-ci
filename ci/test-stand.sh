#!/usr/bin/env bash
# Запись о тестовом стенде в этом репозитории: что выкачено последним успешным deploy-test (ci/test-stand.py record).
# Хранилище - свой prerelease `stand-<UTC>` на каждый выкат с файлом stand.json (релизы репозитория неизменяемы: новый выкат - новый релиз,
# старый не правится); текущее состояние - новейший по имени. Лишнее чистит ci/cleanup.py stand-releases (10 новейших).
# Использование:
#   ci/test-stand.sh fetch <файл>      новейший stand.json в файл; код 3 - записей ещё нет
#   ci/test-stand.sh publish <файл>    опубликовать stand.json новым prerelease
#   ci/test-stand.sh live <файл>       блок `stand` публичного static/index.json стенда (TEST_SERVER_URL) в файл; код 4 - переменной нет или стенд не ответил
#   ci/test-stand.sh test-issues       число открытых Issues с меткой `test` в Sperance/ExileForge (GH_TOKEN с правом чтения Issues там)
# Окружение: GH_TOKEN, GITHUB_REPOSITORY (publish ещё GITHUB_SHA).
set -euo pipefail

here=$(dirname "${BASH_SOURCE[0]}")
. "$here/retry.sh"

latest() {
    netcall read gh release list -R "$GITHUB_REPOSITORY" --limit 100 --json tagName --jq '.[].tagName' | grep -E '^stand-[0-9]{8}T[0-9]{6}Z$' | sort | tail -1 || true
}

case ${1:-} in
    fetch)
        tag=$(latest)
        [[ -n $tag ]] || { echo "test stand: no record of a deploy yet"; exit 3; }
        netcall read gh release download "$tag" -R "$GITHUB_REPOSITORY" -p stand.json -O "$2" --clobber
        echo "test stand: record read" ;;
    publish)
        tag="stand-$(date -u +%Y%m%dT%H%M%SZ)"
        dir=$(mktemp -d)
        cp "$2" "$dir/stand.json"
        netcall once gh release create "$tag" "$dir/stand.json" -R "$GITHUB_REPOSITORY" --target "$GITHUB_SHA" --prerelease --latest=false \
            --title "Test stand" --notes "Last successful deploy to the test stand."
        rm -rf "$dir"
        echo "test stand: record published" ;;
    live)
        [[ -n ${TEST_SERVER_URL:-} ]] || exit 4
        body=$(netcall read curl -fsS --max-time 20 "${TEST_SERVER_URL%/}/static/index.json") || { echo "::warning::the test stand did not answer"; exit 4; }
        printf '%s' "$body" | python3 -I "$here/test-stand.py" live-extract "$2" ;;
    test-issues)
        netcall read gh api --paginate "repos/Sperance/ExileForge/issues?labels=test&state=open&per_page=100" --jq '.[] | select(.pull_request | not) | .number' | wc -l ;;
    *) echo "usage: test-stand.sh fetch <file> | publish <file> | live <file> | test-issues" >&2; exit 2 ;;
esac
