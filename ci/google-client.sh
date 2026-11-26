#!/usr/bin/env bash
# Стенд отдаёт Google-клиента: без него (`GOOGLE_WEB_CLIENT_ID` пуст или потерян) клиент молча прячет строку «Войти через Google»,
# и игрок не понимает, почему кнопки нет. Проверка после выката и в часовом health.
#   bash ci/google-client.sh <адрес стенда>
# Печатает строку «OK google» / «FAIL google» (код 1); адрес не ответил - «SKIP google» и код 0 (доступность ловит проверка https).
# Зовут: job deploy server.yml (после выката боя), job deploy-test server.yml (после выката теста) и часовой health vps.yml.
set -uo pipefail

url=${1:-}
[[ -n $url ]] || { echo 'SKIP google (no stand address)'; exit 0; }
here=$(dirname "${BASH_SOURCE[0]}")
body=$(bash "$here/retry.sh" read curl -fsS --max-time 20 "${url%/}/api/v1/user/google/client" 2>/dev/null) || { echo 'SKIP google (the stand did not answer)'; exit 0; }
if printf '%s' "$body" | grep -q '"clientId":[[:space:]]*"[^"]\+"'; then
    echo 'OK google'
    exit 0
fi
echo 'FAIL google'
echo '::error::the stand gives no Google client id (GOOGLE_WEB_CLIENT_ID is empty or lost): the client hides the sign-in row' >&2
exit 1
