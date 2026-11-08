#!/usr/bin/env bash
# Отметка «check-wip» на коммите приватного репозитория: commit status, его читает хук pre-push (git и gh api) перед пушем в рабочую ветку.
# Использование: ci/check-wip-status.sh <репозиторий> <sha> <success|failure|pending> <описание> <ссылка на прогон>
# Окружение: TOKEN - токен с правом «Commit statuses: write» на репозиторий (секрет CHECK_WIP_TOKEN, а без него EXILEFORGE_TOKEN).
# В журнал идёт только код ответа; тело ответа не выводится.
set -euo pipefail

repo=$1
sha=$2
state=$3
description=$4
url=$5

[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "::error::bad sha '$sha'"; exit 1; }
body=$(python3 -c 'import json, sys; print(json.dumps({"state": sys.argv[1], "context": "check-wip", "description": sys.argv[2][:140], "target_url": sys.argv[3]}))' "$state" "$description" "$url")
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$repo/statuses/$sha" -d "$body")
if [[ $code != 201 ]]; then
    echo "::error::check-wip status on $repo ${sha:0:12} was not written: HTTP $code (the token needs «Commit statuses: write» on $repo: CHECK_WIP_TOKEN or EXILEFORGE_TOKEN)"
    exit 1
fi
echo "check-wip=$state recorded on $repo ${sha:0:12}"
