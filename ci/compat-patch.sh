#!/usr/bin/env bash
# Старый клиент проверяет пару «свой клиент + свой сервер» (ревизия сервера должна совпасть, окно правил - тоже),
# а job `compat` гоняет его против нового сервера с чистой базой: там своё окно ревизий и своя эпоха правил,
# поэтому сверку окна и отпечатка мира ослабляем - их проверяет сторож выката по живому окну.
# Остальное (разбор контента старой моделью, вход, герой, провод) проверяется как есть.
# Патч не применился - красный: иначе проверка совместимости прошла бы молча, ни о чём не сказав.
set -euo pipefail
file=${1:-core/src/test/kotlin/com/sperance/exileforge/core/ServerIntegrationTest.kt}
if [ ! -f "$file" ]; then
    echo "::notice::the oldest client has no contract test at $file: the compat check has nothing to run"
    exit 0
fi
patched=0
if grep -q 'assertEquals(API_REVISION, manifest.revision)' "$file"; then
    sed -i 's/assertEquals(API_REVISION, manifest.revision)/assertTrue(manifest.revision >= API_REVISION, "the server revision is below the client")/' "$file"
    patched=1
fi
if grep -q 'manifest.requireWorkbench()' "$file"; then
    sed -i 's/manifest.requireWorkbench()/Unit/' "$file"
    patched=1
fi
if grep -q 'assertEquals(TestContent.index.hash, index.hash,' "$file"; then
    sed -i 's#assertEquals(TestContent.index.hash, index.hash, .*#assertTrue(index.hash.isNotEmpty(), "the served content has no fingerprint")#' "$file"
    patched=1
fi
if [ "$patched" = 0 ]; then
    echo "::error::the contract test of the oldest client changed: the compat patch must be updated"
    exit 1
fi
echo "compat patch: the revision equality, the window and the world fingerprint of the old client are relaxed"
