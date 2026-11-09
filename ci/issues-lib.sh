#!/usr/bin/env bash
# Закрытие Issues выпуска или выката сервера: общее для close-issues.sh и close-server-issues.sh (подключается через `.`).
# close_issues <репозиторий> <метка> <описание метки> <номера через пробел>: метка создаётся, открытый Issue получает её и закрывается
# выполненным без комментария; метки `ready` («ждёт выпуска») и `in-progress` снимаются; закрытый Issue пропускается. GH_TOKEN - токен
# с Issues: write на репозиторий клиента. Сеть - через ci/retry.sh: правка меток и закрытие идемпотентны (idem), чтение - read.
. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"
close_issues() {
  local repo=$1 label=$2 description=$3 numbers=$4 n state stale
  [ -n "$numbers" ] || { echo "no issues named"; return 0; }
  netcall idem gh label create "$label" -R "$repo" --color 7BE0A6 --description "$description" 2>/dev/null || true
  for n in $numbers; do
    state=$(netcall read gh issue view "$n" -R "$repo" --json state --jq .state 2>/dev/null) || { echo "::warning::issue #$n not found"; continue; }
    [ "$state" = OPEN ] || continue
    netcall idem gh issue edit "$n" -R "$repo" --add-label "$label" >/dev/null
    for stale in ready in-progress; do netcall idem gh issue edit "$n" -R "$repo" --remove-label "$stale" >/dev/null 2>&1 || true; done
    netcall idem gh issue close "$n" -R "$repo" --reason completed >/dev/null
    echo "closed #$n ($label)"
  done
}
