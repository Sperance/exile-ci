#!/usr/bin/env bash
# UI-тесты и строгий смоук R8 на запущенном эмуляторе (job `emulator` в client.yml); вывод - через ci/quiet.sh.
# В текущем каталоге: ui-apks/ (APK UI-тестов) и каталоги строгой R8-сборки (ci/build-tasks.env); SHOTS=true - снимки ключевых экранов.
set -euo pipefail

# Пути строгой R8-сборки - в ci/build-tasks.env
. "$(dirname "$0")/build-tasks.env"

adb install -r ui-apks/app.apk
adb install -r ui-apks/app-androidTest.apk
# Снимки ключевых экранов - только по запуску с shots: релиз их не делает
if [[ ${SHOTS:-false} == true ]]; then only=(); else only=(-e notClass com.sperance.exileforge.ui.KeyScreensShotTest); fi
adb shell am instrument -w "${only[@]}" com.sperance.exileforge.test/androidx.test.runner.AndroidJUnitRunner | tee ui-results.txt
python3 -c "import pathlib,re; text=pathlib.Path('ui-results.txt').read_text(); assert re.search(r'OK \(\d+ tests?\)', text), text"
adb pull /sdcard/Android/data/com.sperance.exileforge/files/design design-preview
# Сборка UI-тестов и строгая R8 - разные APK одного пакета: ставим начисто
adb uninstall com.sperance.exileforge.test
adb uninstall com.sperance.exileforge
adb install -r "$MINIFIED_APK"
adb install -r "$MINIFIED_TEST_APK"
adb shell am instrument -w -e class com.sperance.exileforge.ui.ReleaseSmokeTest com.sperance.exileforge.test/androidx.test.runner.AndroidJUnitRunner | tee release-smoke.txt
python3 -c "import pathlib; text=pathlib.Path('release-smoke.txt').read_text(); assert 'OK (1 test)' in text, text"
