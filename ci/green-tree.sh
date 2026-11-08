#!/usr/bin/env bash
# Отпечаток кода клиента без номера выпуска: дерево коммита (пути и объекты, сабмодуль backend/ - закреплённым коммитом), в котором нет
# RELEASE_NOTES.md, а app/build.gradle.kts взят с обезличенными versionCode и versionName. Коммит `feat: release X` отличается от
# проверенного пушем лишь этими двумя файлами, поэтому его отпечаток совпадает с отпечатком пуша. Вывод: 16 hex-знаков.
# Использование: ci/green-tree.sh <каталог исходников клиента на нужном коммите>
set -euo pipefail

dir=${1:-.}
{
    git -C "$dir" ls-tree -r HEAD | awk -F'\t' '$2 != "RELEASE_NOTES.md" && $2 != "app/build.gradle.kts"'
    printf 'app/build.gradle.kts %s\n' "$(sed -E 's/(versionCode[[:space:]]*=[[:space:]]*)[0-9]+/\1N/; s/(versionName[[:space:]]*=[[:space:]]*)"[^"]*"/\1"V"/' "$dir/app/build.gradle.kts" | sha256sum | cut -d' ' -f1)"
} | sha256sum | cut -c1-16
