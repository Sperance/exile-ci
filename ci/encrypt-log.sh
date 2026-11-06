#!/usr/bin/env bash
# Шифрует файл для публичного артефакта (ci/crypt.sh): вывод сервера в vps.yml. Нет ключа - файл не создаётся, код выхода 1.
# Использование: ci/encrypt-log.sh <входной файл> <выходной файл>
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/crypt.sh"

encrypt log "$1" "$2" || { echo "::error::LOG_AGE_RECIPIENT is not set: the server output is dropped"; exit 1; }
