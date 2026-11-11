#!/usr/bin/env bash
# Версия сервера теста (#1084) и запись о выкате теста: одна логика для server.yml (job deploy-test, пишет) и check-wip.yml (сухой прогон на свежих данных GitHub, не пишет ничего).
# Версия x.y.z_test = версия сервера, выкаченного на бой последним (метка образа коммита из метки server-deployed/<sha>), + k patch; k - порядковый номер
# тестового обновления сервера после того выката (ci/test-stand.py version). Нет метки выката или образа - живой SERVER_URL/static/index.json боя (версия и коммит);
# бой молчит - тест выкатывается с версией своего образа и предупреждением (выход пуст). Падать из-за отсутствия метки боя нельзя: сторож ci/guard-test-version.py.
# Использование:
#   ci/test-server-version.sh version <клон сервера с историей> <sha сервера> <коммит образа теста> <файл выхода>
#       дописывает в файл name=, k=, base= (ci/test-stand.py version); боевая база и запись о прошлом выкате читаются, не пишутся
#   ci/test-server-version.sh record <файл stand.json> <sha клиента> <sha сервера> <коммит образа теста> <тег qa>
#       запись о выкате (ci/test-stand.py record); версия, k и база - из окружения TEST_VERSION, TEST_K, TEST_BASE (пусты - запись без версии)
# Окружение: IMAGE (образ ghcr), SERVER_URL (боевой адрес, может быть пуст), GH_TOKEN, GITHUB_REPOSITORY; вход в ghcr.io с правом чтения пакета.
set -euo pipefail

here=$(dirname "${BASH_SOURCE[0]}")
. "$here/retry.sh"

version() {
    local server=$1 sha=$2 image=$3 out=$4 work deployed base prod="" prod_digest found live code=0 previous
    work=$(mktemp -d)
    netcall read gh api "repos/$GITHUB_REPOSITORY/git/matching-refs/tags/server-deployed/" --paginate --jq '.[].ref' > "$work/deployed.txt"
    base=$(python3 -I "$here/release_state.py" baseline --srv "$server" --head "$sha" --deployed "$work/deployed.txt")
    if [[ $base =~ ^[0-9a-f]{40}$ ]] && found=$(bash "$here/checked-image.sh" "$IMAGE" "$server" "$base"); then
        read -r _ prod_digest <<<"$found"
        prod=$(bash "$here/image-version.sh" "$IMAGE" "$prod_digest") || prod=""
    fi
    if [[ -z $prod && -n ${SERVER_URL:-} ]]; then
        echo "::warning::no record of a prod server deploy: the test server version is counted from the live prod manifest"
        live=$(netcall read curl -fsS --max-time 20 "${SERVER_URL%/}/static/index.json" | python3 -I "$here/test-stand.py" prod-live) || live=""
        read -r prod base <<<"$live"
    fi
    if [[ -z $prod || ! $base =~ ^[0-9a-f]{40}$ ]]; then
        echo "::warning::the prod server version is unknown: the test server keeps the version of its image this time"
        return 0
    fi
    bash "$here/test-stand.sh" fetch "$work/previous.json" || code=$?
    case $code in 0) previous="$work/previous.json" ;; 3) previous=- ;; *) return "$code" ;; esac
    python3 -I "$here/test-stand.py" version "$prod" "$base" "$previous" "$image" "$out"
}

record() {
    local target=$1 client=$2 server=$3 image=$4 tag=$5
    if [[ -n ${TEST_VERSION:-} ]]; then
        python3 -I "$here/test-stand.py" record "$target" "$client" "$server" "$image" "$tag" "${TEST_BASE:-}" "${TEST_K:-}" "$TEST_VERSION"
    else
        python3 -I "$here/test-stand.py" record "$target" "$client" "$server" "$image" "$tag"
    fi
}

case ${1:-} in
    version) [[ $# -eq 5 ]] || { echo "usage: test-server-version.sh version <server clone> <sha> <image commit> <output file>" >&2; exit 2; }; version "$2" "$3" "$4" "$5" ;;
    record) [[ $# -eq 6 ]] || { echo "usage: test-server-version.sh record <stand.json> <client sha> <server sha> <image commit> <qa tag>" >&2; exit 2; }; record "$2" "$3" "$4" "$5" "$6" ;;
    *) echo "usage: test-server-version.sh version|record ..." >&2; exit 2 ;;
esac
