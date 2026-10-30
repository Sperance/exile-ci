#!/usr/bin/env bash
# Ключ подписи релиза из секрета RELEASE_KEYSTORE (base64) в файл: опубликованный APK всегда подписан ключом релиза, поэтому
# каждый ставится поверх прошлого - нет ключа, нет релиза. Значение секрета не печатается.
# Использование: ci/keystore.sh [файл]  (по умолчанию $RUNNER_TEMP/release.jks); путь потом - в RELEASE_KEYSTORE_PATH для Gradle.
set -euo pipefail

if [[ -z ${RELEASE_KEYSTORE:-} ]]; then
    echo "::error::RELEASE_KEYSTORE secret is missing"
    exit 1
fi
echo "$RELEASE_KEYSTORE" | base64 -d >"${1:-$RUNNER_TEMP/release.jks}"
