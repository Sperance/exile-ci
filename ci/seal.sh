#!/usr/bin/env bash
# Зашифрованные артефакты: журналы и артефакты этого репозитория публичны, а сборки клиента (APK UI-тестов не ужат), отчёты
# тестов и снимки экранов раскрывают код. Шифрование - ci/crypt.sh (age с открытым ключом).
#   ci/seal.sh <файл.enc> <пути...>             - упаковать существующие из путей (нет ни одного - ничего не делать); читает владелец
#   ci/seal.sh --transit <файл.enc> <пути...>   - то же для артефактов между job'ами (сборка -> подпись -> публикация): ещё и
#                                                 получатель SEAL_AGE_RECIPIENT, чей закрытый ключ SEAL_AGE_IDENTITY есть у -d
#   ci/seal.sh -d <файл.enc> [каталог]          - распаковать в каталог (по умолчанию текущий); age - нужен SEAL_AGE_IDENTITY
# Владелец читает так: age -d -i key.txt <файл.enc> | tar -xf -
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/crypt.sh"

if [[ $1 == -d ]]; then
    dir=${3:-.}
    mkdir -p "$dir"
    decrypt "$2" | tar -C "$dir" -xf -
    exit 0
fi
kind=log
if [[ $1 == --transit ]]; then
    kind=transit
    shift
fi
out=$1
shift
found=()
for path in "$@"; do [[ -e $path ]] && found+=("$path"); done
((${#found[@]})) || { echo "nothing to seal into $out"; exit 0; }
mkdir -p "$(dirname "$out")"
tar -cf - "${found[@]}" | encrypt "$kind" - "$out" \
    || { echo "::error::cannot seal: LOG_AGE_RECIPIENT$([[ $kind == transit ]] && echo ' and SEAL_AGE_RECIPIENT') is not set"; exit 1; }
echo "sealed ${#found[@]} path(s) into $out"
