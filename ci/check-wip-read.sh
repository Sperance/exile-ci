#!/usr/bin/env bash
# Чтение commit status «check-wip» на коммите приватного репозитория (ворота пуша в client.yml и server.yml, обратное чтение в job record check-wip.yml).
# Использование: ci/check-wip-read.sh [--expect <состояние>] <репозиторий> <sha>
# Окружение: TOKEN - токен с правом «Commit statuses: read» (секрет SOURCE_TOKEN: им же читают ворота пуша).
# В stdout одно слово: success | failure | pending | error | none (статуса нет) | unreadable (чтение не удалось). Состояние проверяется строгим шаблоном;
# ошибка чтения не молчит: `::warning::` с кодом ответа и строка «check-wip status unreadable: <код>» в сводке job, ворота пуша идут как без статуса.
# С --expect нечитаемый статус или состояние, не равное ожидаемому, - `::error::` и код 1 (сторож записи в job record). Тело ответа в журнал не выводится.
set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"

usage="usage: check-wip-read.sh [--expect <state>] <repo> <sha>"
expect=""
if [[ ${1:-} == --expect ]]; then
    expect=${2:?$usage}
    shift 2
fi
repo=${1:?$usage}
sha=${2:?$usage}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "::error::bad sha '$sha'" >&2; exit 2; }

out=$(mktemp)
err=$(mktemp)
trap 'rm -f "$out" "$err"' EXIT

state=""
fail_reason=""

read_state() {
    state=unreadable
    fail_reason=""
    if GH_TOKEN=$TOKEN netcall read gh api "repos/$repo/commits/$sha/statuses?per_page=100" \
        --jq '[.[] | select(.context == "check-wip")] | first | .state // "none"' >"$out" 2>"$err"; then
        local answer
        answer=$(tr -d '[:space:]' <"$out")
        if [[ $answer =~ ^(success|failure|pending|error|none)$ ]]; then
            state=$answer
            return 0
        fi
        fail_reason="unexpected answer"
    else
        fail_reason=$(grep -oh 'HTTP [0-9]*' "$err" "$out" | tail -n1 | sed 's/.*HTTP //' || true)
        fail_reason=${fail_reason:-no answer}
    fi
}

attempts=1
[[ -n $expect ]] && attempts=3
for ((attempt = 1; attempt <= attempts; attempt++)); do
    read_state
    [[ -z $expect || $state == "$expect" ]] && break
    ((attempt < attempts)) && sleep 5
done

if [[ -n $expect ]]; then
    if [[ $state == "$expect" ]]; then
        echo "check-wip=$state read back on $repo ${sha:0:12}"
        exit 0
    fi
    if [[ $state == unreadable ]]; then
        echo "::error::check-wip status unreadable: $fail_reason on $repo ${sha:0:12}: SOURCE_TOKEN needs «Commit statuses: read» on $repo, otherwise the push gates never trust Check wip" >&2
    else
        echo "::error::check-wip status read back as '$state' on $repo ${sha:0:12}, expected '$expect'" >&2
    fi
    exit 1
fi

if [[ $state == unreadable ]]; then
    echo "::warning::check-wip status unreadable: $fail_reason ($repo ${sha:0:12}); the gates run in full" >&2
    [[ -n ${GITHUB_STEP_SUMMARY:-} ]] && echo "check-wip status unreadable: $fail_reason ($repo ${sha:0:12}) - the gates run in full" >>"$GITHUB_STEP_SUMMARY"
fi
echo "$state"
