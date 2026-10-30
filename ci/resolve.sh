#!/usr/bin/env bash
# Целевой коммит и режим прогона client.yml / server.yml: из repository_dispatch (sha в payload, режим - после дефиса типа события:
# client-push, server-deploy) или из ручного запуска (inputs); sha пуст - голова рабочей ветки репозитория. Результат - sha и mode
# в $GITHUB_OUTPUT. Токен только в URL ls-remote, в журнал не попадает.
# Использование: ci/resolve.sh <репозиторий> <ветка> <client|server> <допустимые режимы...>
# Окружение: EVENT, ACTION, PAYLOAD_SHA, INPUT_MODE, INPUT_SHA, TOKEN (SOURCE_TOKEN).
set -euo pipefail

repo=$1
branch=$2
label=$3
shift 3

if [[ $EVENT == repository_dispatch ]]; then
    mode=${ACTION#*-}
    sha=$PAYLOAD_SHA
else
    mode=$INPUT_MODE
    sha=$INPUT_SHA
fi
if [[ -z $sha ]]; then
    sha=$(git ls-remote "https://x-access-token:$TOKEN@github.com/$repo.git" "refs/heads/$branch" | cut -f1)
fi
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "::error::bad $label commit: '$sha'"; exit 1; }
[[ " $* " == *" $mode "* ]] || { echo "::error::bad mode: '$mode'"; exit 1; }
echo "$label $sha, mode $mode"
{ echo "sha=$sha"; echo "mode=$mode"; } >>"$GITHUB_OUTPUT"
