#!/usr/bin/env bash
# Запись о тестовом стенде в этом репозитории: что выкачено последним успешным deploy-test (ci/test-stand.py record).
# Хранилище - свой prerelease `stand-<UTC>` на каждый выкат с файлом stand.json (релизы репозитория неизменяемы: новый выкат - новый релиз,
# старый не правится); текущее состояние - новейший по имени. Лишнее чистит ci/cleanup.py stand-releases (10 новейших).
# Использование:
#   ci/test-stand.sh fetch <файл>      новейший stand.json в файл; код 3 - записей ещё нет
#   ci/test-stand.sh publish <файл>    опубликовать stand.json новым prerelease
#   ci/test-stand.sh live <файл>       блок `stand` публичного static/index.json стенда (TEST_SERVER_URL) в файл; код 4 - переменной нет или стенд не ответил
#   ci/test-stand.sh test-issues       число открытых отчётов с меткой `test` в очереди боевого сервера (REPORTS_API_URL, REPORTS_WORK_TOKEN)
# Окружение: GH_TOKEN, GITHUB_REPOSITORY (publish ещё GITHUB_SHA); test-issues - REPORTS_API_URL и REPORTS_WORK_TOKEN.
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
        [ -n "${REPORTS_API_URL:-}" ] && [ -n "${REPORTS_WORK_TOKEN:-}" ] || { echo 0; exit 0; }
        netcall read curl -sS --fail-with-body -G -H "Authorization: Bearer $REPORTS_WORK_TOKEN" --data state=open "${REPORTS_API_URL%/}/api/v1/reports-work/statuses" \
            | python3 -I -c 'import json, sys; print(int(json.load(sys.stdin)["data"].get("labels", {}).get("test", 0)))' ;;
    *) echo "usage: test-stand.sh fetch <file> | publish <file> | live <file> | test-issues" >&2; exit 2 ;;
esac
