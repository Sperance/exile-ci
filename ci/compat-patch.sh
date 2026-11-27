#!/usr/bin/env bash
# Старый клиент проверяет пару «свой клиент + свой сервер» (ревизия сервера должна совпасть), а job `compat`
# гоняет его против нового сервера: сверку ревизий надо ослабить, остальное (разбор контента, игра, провод) - нет.
# Патч не применился - красный: иначе проверка совместимости прошла бы молча, ни о чём не сказав.
set -euo pipefail
file=${1:-core/src/test/kotlin/com/sperance/exileforge/core/ServerIntegrationTest.kt}
if [ ! -f "$file" ]; then
    echo "::notice::the oldest client has no contract test at $file: the compat check has nothing to run"
    exit 0
fi
if ! grep -q 'assertEquals(API_REVISION, manifest.revision)' "$file"; then
    echo "::error::the contract test of the oldest client changed: the compat patch must be updated"
    exit 1
fi
sed -i 's/assertEquals(API_REVISION, manifest.revision)/assertTrue(manifest.revision >= API_REVISION, "the server revision is below the client")/' "$file"
echo "compat patch: the revision equality of the old client is relaxed to the window"
