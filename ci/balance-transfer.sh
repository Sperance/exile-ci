#!/usr/bin/env bash
# Перенос слепка баланса и текстов клиента между стендами по SSH: `balance-export` одного стенда в stdout, он же в stdin `balance-import` другого.
#   test-to-prod   слепок теста -> бой (Release balance и client): бой выпускает его новой версией баланса, отказ, если код сервера различается;
#   prod-to-test   слепок боя -> тест (первый выкат теста, test-reset): база теста, свои правки теста не затираются;
#   test-summary   только чтение: слепок теста разбирается ci/balance-summary.py, в сводку прогона идут числа (файлы баланса и тексты клиента по языкам),
#                  значений нет; боевой ключ не нужен. Тест без базы боя отказывает (слепок не снимается): строка об этом в сводке, код 0.
# После удачного test-to-prod CI сразу делает prod-to-test: тест узнаёт новый боевой мир (его хэш лежит в базе теста), иначе следующий перенос бой
# отклонит как основанный на старом боевом мире. Сбой этой второй передачи - предупреждение, не красный прогон.
# Единственное место CI, где в одной команде работают оба ключа (сторож ci/guard-test-vps.py): каждый ключ привязан на VPS к update.sh своего проекта.
# Публичный журнал: слепок лежит только во временном каталоге раннера и удаляется; вывод серверов - в зашифрованном журнале logs/balance-<направление>.log.enc.
# Отказ или сбой любого шага - красный прогон (::error::, код 1).
# Окружение: VPS_HOST, PROD_KEY, TEST_KEY, VPS_HOST_KEY, LOG_AGE_RECIPIENT. Использование: ci/balance-transfer.sh test-to-prod | prod-to-test
set -uo pipefail

here=$(dirname "${BASH_SOURCE[0]}")
direction=${1:-}
need_prod=1
case $direction in
    test-to-prod) from_key=$TEST_KEY to_key=$PROD_KEY ;;
    prod-to-test) from_key=$PROD_KEY to_key=$TEST_KEY ;;
    test-summary) from_key=$TEST_KEY to_key='' need_prod=0 ;;
    *) echo "::error::usage: balance-transfer.sh test-to-prod | prod-to-test | test-summary"; exit 2 ;;
esac
[[ -n ${VPS_HOST:-} && -n $from_key && -n ${LOG_AGE_RECIPIENT:-} ]] && { ((need_prod == 0)) || [[ -n $to_key ]]; } || { echo "::error::DEPLOY_HOST, DEPLOY_SSH_KEY, DEPLOY_SSH_KEY_TEST or LOG_AGE_RECIPIENT is not set"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
install -m 600 /dev/null "$tmp/from" && printf '%s\n' "$from_key" > "$tmp/from"
if [[ -n $to_key ]]; then install -m 600 /dev/null "$tmp/to" && printf '%s\n' "$to_key" > "$tmp/to"; fi
mkdir -p logs

finish() {
    local code=$1 step=$2
    cat "$tmp/export.err" "$tmp/import.out" 2>/dev/null > "$tmp/all.txt" || true
    bash "$here/encrypt-log.sh" "$tmp/all.txt" "logs/balance-$direction.log.enc" || true
    if ((code != 0)); then
        echo "::error::balance transfer $direction refused or failed at $step (exit $code): the server answer is in the encrypted artifact"
    else
        echo "balance transfer $direction: done"
    fi
    exit "$code"
}

export_snapshot() {
    local code=0
    VPS_HOST=$VPS_HOST VPS_KEY_FILE="$tmp/from" bash "$here/vps-ssh.sh" balance-export </dev/null >"$tmp/snapshot.gz" 2>"$tmp/export.err" || code=$?
    return $code
}

if [[ $direction == test-summary ]]; then
    if export_snapshot && [[ -s $tmp/snapshot.gz ]] && gzip -t "$tmp/snapshot.gz" 2>/dev/null; then
        python3 -I "$here/balance-summary.py" "$tmp/snapshot.gz" "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
    else
        printf '### Баланс теста\n- Слепок не снят: тест отказал или не отвечает (ответ сервера - в зашифрованном журнале).\n' >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
    fi
    cat "$tmp/export.err" > "$tmp/all.txt" 2>/dev/null || true
    bash "$here/encrypt-log.sh" "$tmp/all.txt" "logs/balance-$direction.log.enc" || true
    exit 0
fi

code=0
export_snapshot || code=$?
((code == 0)) || finish "$code" export
[[ -s $tmp/snapshot.gz ]] && gzip -t "$tmp/snapshot.gz" 2>/dev/null || finish 1 "export (empty or damaged snapshot)"
echo "snapshot: $(wc -c < "$tmp/snapshot.gz") bytes"
VPS_HOST=$VPS_HOST VPS_KEY_FILE="$tmp/to" bash "$here/vps-ssh.sh" balance-import <"$tmp/snapshot.gz" >"$tmp/import.out" 2>&1 || code=$?
if ((code == 0)) && [[ $direction == test-to-prod ]]; then
    refresh_code=0
    VPS_HOST=$VPS_HOST VPS_KEY_FILE="$tmp/to" bash "$here/vps-ssh.sh" balance-export </dev/null >"$tmp/prod.gz" 2>>"$tmp/export.err" || refresh_code=$?
    if ((refresh_code == 0)) && [[ -s $tmp/prod.gz ]] && gzip -t "$tmp/prod.gz" 2>/dev/null; then
        VPS_HOST=$VPS_HOST VPS_KEY_FILE="$tmp/from" bash "$here/vps-ssh.sh" balance-import <"$tmp/prod.gz" >>"$tmp/import.out" 2>&1 || refresh_code=$?
    else
        refresh_code=1
    fi
    ((refresh_code == 0)) && echo "test base refreshed with the new prod world" || echo "::warning::the test base was not refreshed (exit $refresh_code): refresh it with VPS -> test-base before the next transfer"
fi
finish "$code" import
