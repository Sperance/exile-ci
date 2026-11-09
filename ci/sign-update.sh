#!/usr/bin/env bash
# Подпись описания обновления: Ed25519 над байтами update.json как есть, 128 hex в update.json.sig рядом (клиент: ManifestSignature).
# Общая для релиза (job `release`) и тестовой сборки (job `qa-release`) client.yml. Нет UPDATE_SIGNING_KEY - файл без подписи, предупреждение.
# Использование: ci/sign-update.sh <путь к update.json>; окружение: UPDATE_SIGNING_KEY, RUNNER_TEMP.
set -euo pipefail

manifest=${1:?usage: sign-update.sh <update.json>}
if [ -z "${UPDATE_SIGNING_KEY:-}" ]; then echo "::warning::UPDATE_SIGNING_KEY is not set: update.json goes out unsigned"; exit 0; fi
umask 077
printf '%s\n' "$UPDATE_SIGNING_KEY" > "$RUNNER_TEMP/update-signing.pem"
openssl pkeyutl -sign -rawin -inkey "$RUNNER_TEMP/update-signing.pem" -in "$manifest" -out "$RUNNER_TEMP/update.sig.bin"
rm -f "$RUNNER_TEMP/update-signing.pem"
od -An -v -tx1 "$RUNNER_TEMP/update.sig.bin" | tr -d ' \n' > "$manifest.sig"
[ "$(wc -c < "$manifest.sig")" = 128 ] || { echo "::error::update.json signature has a wrong length"; exit 1; }
echo "update.json signed"
