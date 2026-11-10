#!/usr/bin/env bash
# Адрес боя отдаёт бой, а не тестовый стенд: публичный <адрес боя>/static/index.json без поля `stand` (его пишет только сервер теста).
# Тест и бой на одном VPS делят Caddy; голое имя сервиса `game` в Caddyfile боя в общей сети edge ведёт и на тест (rules-md/server/test-server.md сервера).
#   bash ci/prod-route.sh <адрес боя>
# Печатает строку для ci/vps_health.py: «OK route» / «FAIL route» (код 1); адрес не ответил - «SKIP route» и код 0 (недоступность ловит проверка https).
# Зовут: job deploy-test server.yml (после выката теста) и часовой health vps.yml.
set -uo pipefail

url=${1:-}
[[ -n $url ]] || { echo 'SKIP route (no prod address)'; exit 0; }
here=$(dirname "${BASH_SOURCE[0]}")
body=$(bash "$here/retry.sh" read curl -fsS --max-time 20 "${url%/}/static/index.json" 2>/dev/null) || { echo 'SKIP route (prod address did not answer)'; exit 0; }
if grep -q '"stand":{' <<<"$body"; then
    echo 'FAIL route'
    echo '::error::the prod address serves the test stand (index.json carries stand)' >&2
    exit 1
fi
echo 'OK route'
