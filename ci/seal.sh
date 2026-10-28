#!/usr/bin/env bash
# Зашифрованные артефакты: журналы и артефакты этого репозитория публичны, а сборки клиента (APK UI-тестов не ужат), отчёты
# тестов и снимки экранов раскрывают код. Ключ - LOG_KEY (AES-256, openssl); владелец ключа расшифровывает так же, с -d.
#   ci/seal.sh <файл.enc> <пути...>     - упаковать существующие из путей (нет ни одного - ничего не делать)
#   ci/seal.sh -d <файл.enc> [каталог]  - распаковать в каталог (по умолчанию текущий)
set -euo pipefail

[[ -n ${LOG_KEY:-} ]] || { echo "::error::LOG_KEY is not set"; exit 1; }
if [[ $1 == -d ]]; then
    dir=${3:-.}
    mkdir -p "$dir"
    openssl enc -d -aes-256-cbc -pbkdf2 -pass env:LOG_KEY -in "$2" | tar -C "$dir" -xf -
    exit 0
fi
out=$1
shift
found=()
for path in "$@"; do [[ -e $path ]] && found+=("$path"); done
((${#found[@]})) || { echo "nothing to seal into $out"; exit 0; }
mkdir -p "$(dirname "$out")"
tar -cf - "${found[@]}" | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:LOG_KEY -out "$out"
echo "sealed ${#found[@]} path(s) into $out"
