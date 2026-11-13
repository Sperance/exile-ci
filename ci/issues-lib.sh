#!/usr/bin/env bash
# Закрытие Issues выпуска или выката сервера: общее для close-issues.sh и close-server-issues.sh (подключается через `.`).
# close_issues <репозиторий> <метка> <описание метки> <номера через пробел>: метка создаётся, открытый Issue получает её и закрывается
# выполненным без комментария; метки `ready` («ждёт выпуска»), `in-progress` и `verified` («проверено автором») снимаются; закрытый Issue пропускается. GH_TOKEN - токен
# с Issues: write на репозиторий клиента. Сеть - через ci/retry.sh: правка меток и закрытие идемпотентны (idem), чтение - read.
# Очередь отчётов боевого сервера (этап 1 ухода от Issues): заданы REPORTS_API_URL и REPORTS_WORK_TOKEN - каждый номер сначала закрывается
# рабочим API (`POST /api/v1/reports-work/close`, метка версии; сервер сам закрывает и зеркало GitHub), номер зеркала из ответа заменяет номер
# очереди в проверке GitHub ниже. Не заданы или ответ не пришёл - номер идёт в GitHub как прежде. Ответы и ключ в журнал не попадают.
. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"
queue_close() {
  local n=$1 label=$2 body reply head
  [ -n "${REPORTS_API_URL:-}" ] && [ -n "${REPORTS_WORK_TOKEN:-}" ] || { echo -; return 0; }
  head=$(netcall read curl -sS --fail-with-body -G -H "Authorization: Bearer $REPORTS_WORK_TOKEN" --data "number=$n" "${REPORTS_API_URL%/}/api/v1/reports-work/get") \
    || { echo "::warning::report queue did not answer for #$n" >&2; echo -; return 0; }
  head=$(printf '%s' "$head" | python3 -I -c 'import json, sys; s = json.load(sys.stdin)["data"]["summary"]; print(("closed " if s.get("state") == "closed" else "open ") + str(int(s.get("githubNumber", 0))))' 2>/dev/null) \
    || { echo "::warning::report queue answer for #$n is unreadable" >&2; echo -; return 0; }
  case $head in closed*) echo "done ${head#closed }"; return 0 ;; esac
  body=$(python3 -I -c 'import json, sys; print(json.dumps({"number": int(sys.argv[1]), "reason": "completed", "label": sys.argv[2]}))' "$n" "$label")
  reply=$(netcall idem curl -sS --fail-with-body -X POST -H "Authorization: Bearer $REPORTS_WORK_TOKEN" -H 'Content-Type: application/json' --data-binary "$body" "${REPORTS_API_URL%/}/api/v1/reports-work/close") \
    || { echo "::warning::report queue did not close #$n" >&2; echo -; return 0; }
  printf '%s' "$reply" | python3 -I -c 'import json, sys; print(int(json.load(sys.stdin)["data"].get("githubNumber", 0)))' 2>/dev/null || { echo "::warning::report queue answer for #$n is unreadable" >&2; echo -; }
}
close_issues() {
  local repo=$1 label=$2 description=$3 numbers=$4 n state stale queued
  [ -n "$numbers" ] || { echo "no issues named"; return 0; }
  netcall idem gh label create "$label" -R "$repo" --color 7BE0A6 --description "$description" 2>/dev/null || true
  for n in $numbers; do
    queued=$(queue_close "$n" "$label")
    case $queued in
      -) ;;
      done*) echo "#$n is already closed in the report queue"; continue ;;
      0) echo "closed #$n in the report queue ($label)"; continue ;;
      *) echo "closed #$n in the report queue ($label)"; n=$queued ;;
    esac
    state=$(netcall read gh issue view "$n" -R "$repo" --json state --jq .state 2>/dev/null) || { echo "::warning::issue #$n not found"; continue; }
    [ "$state" = OPEN ] || continue
    netcall idem gh issue edit "$n" -R "$repo" --add-label "$label" >/dev/null
    for stale in ready in-progress verified; do netcall idem gh issue edit "$n" -R "$repo" --remove-label "$stale" >/dev/null 2>&1 || true; done
    netcall idem gh issue close "$n" -R "$repo" --reason completed >/dev/null
    echo "closed #$n ($label)"
  done
}
