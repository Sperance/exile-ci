#!/usr/bin/env bash
# Запуск шага без вывода в публичный журнал Actions: код сервера приватный, а журналы этого репозитория видны всем.
# В журнал попадают только имя шага, код выхода и время. Полный вывод при падении шифруется ключом LOG_KEY
# (AES-256, openssl) в $GITHUB_WORKSPACE/logs/<имя>.log.enc - его выкладывает артефакт, читает только владелец ключа:
#   openssl enc -d -aes-256-cbc -pbkdf2 -pass env:LOG_KEY -in <имя>.log.enc
# Использование: ci/quiet.sh <имя> <команда> [аргументы...]
set -uo pipefail

name=$1
shift
mkdir -p "$GITHUB_WORKSPACE/logs"
log=$(mktemp)
start=$(date +%s)
"$@" >"$log" 2>&1
code=$?
echo "$name: exit $code in $(($(date +%s) - start))s"
if ((code != 0)); then
    if [[ -n ${LOG_KEY:-} ]]; then
        openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:LOG_KEY -in "$log" -out "$GITHUB_WORKSPACE/logs/$name.log.enc"
        echo "::error::$name failed (exit $code): full log in the encrypted artifact"
    else
        echo "::error::$name failed (exit $code): LOG_KEY is not set, the log is dropped"
    fi
fi
rm -f "$log"
exit "$code"
