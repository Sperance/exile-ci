#!/usr/bin/env bash
# Запуск другого workflow этого репозитория и ожидание его итога: единственное место, где CI зовёт `gh workflow run` (сторож ci/guard-dispatch.py).
# Запуск без ожидания («выстрелил и забыл») прятал красные прогоны: вызывающий заканчивался зелёным, а запущенный падал, и никто не замечал.
# Использование: bash ci/dispatch-wait.sh <workflow.yml> <ref> [-f ключ=значение ...]
# Как работает:
#   1. к входам добавляется `caller=<GITHUB_RUN_ID>-<GITHUB_RUN_ATTEMPT>-<случайное>`; запущенный workflow объявляет вход `caller` и несёт его в `run-name`
#      (display_title прогона), так прогон находится однозначно, даже если рядом идут другие запуски того же workflow;
#   2. запуск - `retry.sh once` (повторяется только когда запрос заведомо не дошёл), прогон ищется в списке workflow_dispatch-прогонов
#      по метке в display_title (до 60 попыток с паузой 10 с - это в CI, не в сессии агента);
#   3. `gh run watch --exit-status` (retry.sh read) ждёт итог; красный итог - `::error::<workflow> run <ссылка> failed` и код 1, в сводку шага идёт строка со ссылкой.
# DISPATCH_WAIT_SOFT=1 - красный запущенный прогон только предупреждение (::warning:: со ссылкой), код 0: для постов в Telegram и прочего, что выпуск не держит.
# Окружение: GH_TOKEN (право actions: write и read), GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT. Журнал публичен: в него идут только имя workflow,
# номер и ссылка прогона и имена упавших job'ов.
# Взаимные ожидания (тупик): вызывающий job держит свою concurrency-группу, пока ждёт; запущенный прогон не должен ждать ту же группу или вызывающий прогон.
# Каждая пара проверена и описана в шапке workflow, что зовёт этот файл.
set -euo pipefail

here=$(dirname "${BASH_SOURCE[0]}")
. "$here/retry.sh"

workflow=${1:?usage: dispatch-wait.sh <workflow.yml> <ref> [-f key=value ...]}
ref=${2:?usage: dispatch-wait.sh <workflow.yml> <ref> [-f key=value ...]}
shift 2

repo=$GITHUB_REPOSITORY
caller="${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:-1}-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
soft=${DISPATCH_WAIT_SOFT:-0}

summary() {
    [[ -z ${GITHUB_STEP_SUMMARY:-} ]] || echo "$1" >> "$GITHUB_STEP_SUMMARY"
}

netcall once gh workflow run "$workflow" -R "$repo" --ref "$ref" -f caller="$caller" "$@"

id=""
for attempt in $(seq 1 60); do
    id=$(netcall read gh api "repos/$repo/actions/workflows/$workflow/runs?event=workflow_dispatch&per_page=50" \
        --jq ".workflow_runs[] | select(.display_title | contains(\"$caller\")) | .id" | head -1 || true)
    [[ -z $id ]] || break
    echo "run of $workflow with $caller is not listed yet (attempt $attempt of 60)"
    sleep 10
done
[[ -n $id ]] || { echo "::error::$workflow was dispatched, but its run was not found in 10 minutes: does its run-name carry inputs.caller?"; exit 1; }

url="$GITHUB_SERVER_URL/$repo/actions/runs/$id"
echo "waiting for $workflow run $url"
summary "- $workflow: [run $id]($url)"

code=0
netcall read gh run watch "$id" -R "$repo" --exit-status --interval 30 > /dev/null || code=$?
conclusion=$(netcall read gh api "repos/$repo/actions/runs/$id" --jq .conclusion || echo unknown)
if [[ $code -eq 0 && $conclusion == success ]]; then
    echo "$workflow run $url: success"
    summary "  - $conclusion"
    exit 0
fi
failed=$(netcall read gh api "repos/$repo/actions/runs/$id/jobs?per_page=100" --jq '[.jobs[] | select(.conclusion == "failure" or .conclusion == "cancelled") | .name] | join(", ")' || true)
summary "  - $conclusion${failed:+ ($failed)}"
if [[ $soft == 1 ]]; then
    echo "::warning::$workflow run $url finished with $conclusion${failed:+ ($failed)}: the caller goes on"
    exit 0
fi
echo "::error::$workflow run $url failed ($conclusion${failed:+: $failed})"
exit 1
