#!/usr/bin/env bash
# Список Issue тестовой сборки для тестового сервера: маркер <!-- issues: N,M --> из тела приватного предрелиза qa-<n> клиента (его кладёт client.yml
# перед выкатом теста) уходит командой `test-build <n> <N,M|->` на update.sh теста тем же ключом, что и выкат. Сервер теста читает файл
# transfer/test-builds/qa-<n>.txt, GitHub остаётся запасным (TestBuildLedger). Старый update.sh команду отвергает: это предупреждение, не провал.
#   test-build.sh issues      тело релиза в stdin -> stdout: номера через запятую или `-` (маркера нет или он битый - код 3)
#   test-build.sh send <qa-тег> <файл с телом релиза>   нужны VPS_HOST, VPS_KEY_FILE, VPS_HOST_KEY
set -uo pipefail

HERE=$(dirname "${BASH_SOURCE[0]}")

issues_of() {
    local marker list
    marker=$(grep -o '<!--[[:space:]]*issues:[^>]*-->' | head -1) || true
    [[ -n $marker ]] || return 3
    list=$(sed -e 's/<!--[[:space:]]*issues:[[:space:]]*//' -e 's/[[:space:]]*-->//' -e 's/[[:space:]]//g' <<<"$marker")
    if [[ -z $list ]]; then
        echo -
        return 0
    fi
    [[ $list =~ ^[0-9]{1,9}(,[0-9]{1,9})*$ ]] || return 3
    echo "$list"
}

send() {
    local tag=$1 body=$2 qa list
    [[ $tag =~ ^qa-([0-9]{1,6})$ ]] || { echo "::warning::test-build: '$tag' is not a test build tag"; return 0; }
    qa=${BASH_REMATCH[1]}
    list=$(issues_of <"$body") || { echo "::warning::test-build: no issue list in the body of $tag; the test server falls back to reading GitHub"; return 0; }
    if bash "$HERE/quiet.sh" test-build bash "$HERE/vps-ssh.sh" "test-build $qa $list"; then
        echo "test-build: $tag sent ($list)"
    else
        echo "::warning::test-build was not accepted by the test stand; the test server falls back to reading GitHub - update update.sh of the test stand from deploy/ of the server repository"
    fi
    return 0
}

case ${1:-} in
    issues) issues_of ;;
    send) send "${2:?qa tag}" "${3:?body file}" ;;
    *) echo "usage: test-build.sh issues | send <qa-tag> <body file>" >&2; exit 2 ;;
esac
