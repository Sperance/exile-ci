#!/usr/bin/env bash
# Одноразовое хранилище ключа для СБОРКИ без секретов: Gradle клиента (app/build.gradle.kts) подписывает релизные варианты ключом
# из RELEASE_KEYSTORE_PATH, а сборка для Google Play без хранилища падает. Здесь ключ создаётся заново, живёт в $RUNNER_TEMP одного
# job'а и ничего не значит: настоящий ключ релиза есть только у job'а подписи (ci/sign.sh), он снимает эту подпись и ставит свою.
# Использование: eval "$(bash ci/build-keystore.sh)" - выставляет RELEASE_KEYSTORE_PATH и пароли в окружении шага.
set -euo pipefail

store="$RUNNER_TEMP/build-only.jks"
rm -f "$store"
keytool -genkeypair -keystore "$store" -storetype PKCS12 -storepass build-only -keypass build-only -alias build-only \
    -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=build-only' >/dev/null 2>&1
cat <<VARS
export RELEASE_KEYSTORE_PATH='$store'
export RELEASE_KEYSTORE_PASSWORD='build-only'
export RELEASE_KEY_ALIAS='build-only'
export RELEASE_KEY_PASSWORD='build-only'
VARS
