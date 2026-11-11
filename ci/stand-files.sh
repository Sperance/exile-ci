#!/usr/bin/env bash
# Файлы тестового стенда на VPS обновляет сам CI перед каждым выкатом теста: update.sh и compose.yaml, compose.override.yaml, verify.sh, mongo-health.js
# из закреплённого checkout сервера уходят одним gzip tar командой `stand-files <sha256>` (update.sh теста принимает её только с точным списком имён
# STAND_FILES, проверяет sha256 и `bash -n`, меняет изменённые файлы атомарно с копией; .env, секреты и Caddyfile не затрагиваются).
# Список здесь обязан совпадать со STAND_FILES в deploy/update.sh сервера (сверяют build и ci/guard-test-version.py). Содержимое файлов в журнал не
# выводится: печатаются только имена из списка и фиксированные строки update.sh.
#   stand-files.sh names                                 список имён
#   stand-files.sh build <каталог сервера> <архив.tgz>   детерминированный архив, в stdout его sha256
#   stand-files.sh send <каталог сервера>                build + отправка (VPS_HOST, VPS_KEY_FILE, VPS_HOST_KEY); старый update.sh - предупреждение, не провал
set -uo pipefail

HERE=$(dirname "${BASH_SOURCE[0]}")
NAMES=(update.sh compose.yaml compose.override.yaml verify.sh mongo-health.js)
LIMIT=2097152

source_of() {
    local root=$1 name=$2
    if [[ $name == update.sh ]]; then printf '%s/deploy/update.sh' "$root"; else printf '%s/deploy/test/%s' "$root" "$name"; fi
}

server_names() {
    sed -n 's/^STAND_FILES=(\(.*\))$/\1/p' "$1" | head -1
}

build() {
    local root=$1 out=$2 name stage declared
    stage=$(mktemp -d)
    trap 'rm -rf "$stage"' RETURN
    declared=$(server_names "$(source_of "$root" update.sh)")
    [[ -n $declared ]] || return 3
    [[ $declared == "${NAMES[*]}" ]] || { echo "::error::STAND_FILES of update.sh differs from ci/stand-files.sh" >&2; return 1; }
    for name in "${NAMES[@]}"; do
        [[ -f $(source_of "$root" "$name") && ! -L $(source_of "$root" "$name") ]] || { echo "::error::$name is missing in the pinned server" >&2; return 1; }
        cp "$(source_of "$root" "$name")" "$stage/$name" || return 1
    done
    bash -n "$stage/update.sh" || { echo "::error::update.sh does not pass bash -n" >&2; return 1; }
    (cd "$stage" && tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --format=gnu -cf - "${NAMES[@]}") | gzip -n -9 >"$out" || return 1
    (($(stat -c %s "$out") <= LIMIT)) || { echo "::error::stand files archive is over $LIMIT bytes" >&2; return 1; }
    sha256sum "$out" | cut -d' ' -f1
}

send() {
    local root=$1 work sha out code=0 line
    work=$(mktemp -d)
    trap 'rm -rf "$work"' RETURN
    sha=$(build "$root" "$work/stand.tgz") || code=$?
    if ((code == 3)); then
        echo "::warning::the pinned server has no stand-files list: stand files are not updated"
        return 0
    fi
    ((code == 0)) || return 1
    [[ $sha =~ ^[0-9a-f]{64}$ ]] || { echo "::error::no archive hash"; return 1; }
    out=$work/out.txt
    if bash "$HERE/vps-ssh.sh" "stand-files $sha" <"$work/stand.tgz" >"$out" 2>&1; then
        while IFS= read -r line; do
            [[ $line =~ ^stand-files:\ (заменены\ [a-z.\ -]+|без\ изменений|следующий\ деплой\ пересоздаст\ контейнер\ игры)$ ]] && echo "$line"
        done <"$out"
        return 0
    fi
    if grep -q 'Неизвестная команда\|не поддерживается' "$out"; then
        echo "::warning::update.sh of the test stand is too old for self-update: run the one-time bootstrap"
        return 0
    fi
    while IFS= read -r line; do
        [[ $line =~ ^stand-files:\ [^[:cntrl:]]{1,80}$ ]] && echo "$line"
    done <"$out"
    echo "::error::stand-files was refused or failed on the test stand"
    return 1
}

case ${1:-} in
    names) echo "${NAMES[*]}" ;;
    build) build "${2:?server dir}" "${3:?archive}" ;;
    send) send "${2:?server dir}" ;;
    *) echo "usage: stand-files.sh names | build <server dir> <archive> | send <server dir>" >&2; exit 2 ;;
esac
