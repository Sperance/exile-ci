#!/usr/bin/env bash
# Запуск шага без вывода в публичный журнал Actions: код сервера приватный, а журналы этого репозитория видны всем.
# В журнал попадают только имя шага, код выхода и время. Полный вывод при падении шифруется (ci/crypt.sh: age с открытым ключом
# LOG_AGE_RECIPIENT, пока он не задан - переходный openssl с LOG_KEY) в $GITHUB_WORKSPACE/logs/<имя>.log.enc - его выкладывает
# артефакт, читает только владелец ключа:
#   age -d -i key.txt <имя>.log.enc
# Использование: ci/quiet.sh <имя> <команда> [аргументы...]
set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/crypt.sh"

name=$1
shift
mkdir -p "$GITHUB_WORKSPACE/logs"
log=$(mktemp)
start=$(date +%s)
"$@" >"$log" 2>&1
code=$?
echo "$name: exit $code in $(($(date +%s) - start))s"
if ((code != 0)); then
    if encrypt log "$log" "$GITHUB_WORKSPACE/logs/$name.log.enc"; then
        echo "::error::$name failed (exit $code): full log in the encrypted artifact"
    else
        echo "::error::$name failed (exit $code): LOG_AGE_RECIPIENT is not set, the log is dropped"
    fi
fi
rm -f "$log"
exit "$code"
