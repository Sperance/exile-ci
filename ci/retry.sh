#!/usr/bin/env bash
# Сетевые вызовы CI из bash - только через этот файл (сторож ci/guard-network.py падает на голый gh, curl, git clone/fetch/ls-remote).
# Питоновский близнец - ci/net.py (urllib и requests); режимы и правила у них одни.
#
#   netcall <режим> <команда...>            после `. ci/retry.sh`
#   bash ci/retry.sh <режим> <команда...>   одной строкой, в том числе внутри $( ), каналов и функций workflow
#
# Режим говорит, что можно повторять после сбоя; паузы между попытками 5, 10, 20 с (всего до 4 попыток), код возврата и вывод - последней:
#   read   чтение или скачивание: gh api GET, gh release view|list|download, curl GET, git clone|fetch|ls-remote. Повтор безвреден.
#   idem   запись, повтор которой даёт то же состояние: gh release upload --clobber, delete, delete-asset, правка меток Issue, commit status,
#          тег, чьё «уже есть» терпит вызывающий. Повторяется, как read.
#   once   запись, которую нельзя повторять вслепую: создание релиза, Issue, запуск workflow, пост в Telegram. Повтор только когда сбой
#          доказывает, что запрос не дошёл (имя не найдено, соединение отклонено или не установилось); ответ 5xx, обрыв после отправки и
#          таймаут ответа - не доказательство, ошибка остаётся ошибкой, шаг запускают заново осознанно.
# Повторяется только временное: ответы 5xx, таймауты, обрывы, сбои DNS и TLS, «RPC failed», «early EOF». Отказ по существу (401, 403, 404, 422,
# «already exists») возвращается сразу. curl с -w '%{http_code}' и выводом ровно 5xx повторяется как ответ 5xx.
# stdin команды - /dev/null: повтор не получил бы его заново. В вывод попадают номер попытки и класс сбоя; аргументы (в них бывают токены) не печатаются.
# Старый `retry <команда>` - для чтения сразу после пуша: хранилище Git на GitHub отдаёт его с отставанием, «не найдено» изредка верно лишь через секунды.

NET_DELAYS=(5 10 20)
NET_NOT_SENT='could not resolve host|temporary failure resolving|no such host|name or service not known|temporary failure in name resolution|connection refused|failed to connect|couldn.t connect|network is unreachable|tls handshake timeout|ssl connection timeout|dial tcp .*(refused|timeout)'
NET_TRANSIENT='http 5[0-9][0-9]|failed to fetch|unable to fetch some archives|hash sum mismatch|returned error: 5[0-9][0-9]|error: 5[0-9][0-9]|bad gateway|service unavailable|gateway time-?out|internal server error|timed out|timeout|connection reset|reset by peer|unexpected disconnect|early eof|rpc failed|remote end hung up|broken pipe|unexpected eof|stream error|server closed|tls: |empty reply|transfer closed|operation too slow|http/2 stream'

netcall_class() {
    local mode=$1 code=$2 text=$3 command=$4
    local lower=${text,,}
    if ((code == 0)); then
        [[ $command == curl && $mode != once && $text =~ ^[[:space:]]*5[0-9][0-9][[:space:]]*$ ]] || return 1
        echo "HTTP 5xx"
        return 0
    fi
    if [[ $command == curl && ($code == 6 || $code == 7) ]] || [[ $lower =~ $NET_NOT_SENT ]]; then
        echo "not sent"
        return 0
    fi
    [[ $mode == once ]] && return 1
    if [[ $command == curl && ($code == 18 || $code == 28 || $code == 35 || $code == 52 || $code == 55 || $code == 56) ]] || [[ $lower =~ $NET_TRANSIENT ]]; then
        echo "transient"
        return 0
    fi
    return 1
}

netcall() {
    local mode=$1
    shift
    case $mode in read | idem | once) ;; *)
        echo "netcall: unknown mode '$mode' (read, idem, once)" >&2
        return 2
        ;;
    esac
    local attempt=0 code out err kind text delay command=${1##*/}
    out=$(mktemp) err=$(mktemp)
    while :; do
        code=0
        "$@" >"$out" 2>"$err" </dev/null || code=$?
        if ((code == 0)); then text=$(cat "$out"); else text=$(cat "$out" "$err"); fi
        kind=$(netcall_class "$mode" "$code" "$text" "$command") || kind=""
        if [[ -z $kind ]] || ((attempt >= ${#NET_DELAYS[@]})); then
            cat "$out"
            cat "$err" >&2
            rm -f "$out" "$err"
            return "$code"
        fi
        delay=${NET_DELAYS[$attempt]}
        attempt=$((attempt + 1))
        echo "::notice::network call failed ($kind, mode $mode), retry $attempt of ${#NET_DELAYS[@]} in ${delay}s" >&2
        sleep "$delay"
    done
}

retry() {
    local attempt=1 delay=2
    until "$@"; do
        ((attempt < 4)) || return 1
        echo "::notice::GitHub read failed, retry $attempt of 3 in ${delay}s" >&2
        sleep "$delay"
        attempt=$((attempt + 1)) delay=$((delay * 2))
    done
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    (($# >= 2)) || { echo "usage: retry.sh read|idem|once <command...>" >&2; exit 2; }
    netcall "$@"
fi
