#!/usr/bin/env bash
# Отметка «check-wip» на коммите приватного репозитория: commit status, его читает хук pre-push (git и gh api) перед пушем в рабочую ветку.
# Использование: ci/check-wip-status.sh <репозиторий> <sha> <success|failure|pending> <описание> <ссылка на прогон>
# Окружение: TOKEN - токен с правом «Commit statuses: write» на репозиторий (секрет CHECK_WIP_TOKEN, а без него EXILEFORGE_TOKEN).
# В журнал идёт только код ответа; тело ответа не выводится. Запись повторима (idem): тот же статус на тот же sha ничего не меняет.
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"

repo=$1
sha=$2
state=$3
description=$4
url=$5

[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "::error::bad sha '$sha'"; exit 1; }
err=$(mktemp)
trap 'rm -f "$err"' EXIT
if ! GH_TOKEN=$TOKEN netcall idem gh api -X POST "repos/$repo/statuses/$sha" -f "state=$state" -f context=check-wip \
    -f "description=${description:0:140}" -f "target_url=$url" >/dev/null 2>"$err"; then
    code=$(grep -o 'HTTP [0-9]*' "$err" | tail -n1 || true)
    echo "::error::check-wip status on $repo ${sha:0:12} was not written: ${code:-no answer} (the token needs «Commit statuses: write» on $repo: CHECK_WIP_TOKEN or EXILEFORGE_TOKEN)"
    exit 1
fi
echo "check-wip=$state recorded on $repo ${sha:0:12}"
