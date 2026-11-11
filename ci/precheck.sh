#!/usr/bin/env bash
# Самопроверка exile-ci: правки .github/** и ci/** проходят её перед пушем в wip, тот же набор идёт workflow selfcheck.yml на пуше в main.
# Секретов и сети не нужно (20-30 с). Шаги:
#   syntax   YAML каждого файла .github/**.yml разбирается, каждый блок run проходит `bash -n` (ci/check-syntax.py; нужен модуль yaml)
#   shell    `bash -n` каждого ci/**.sh и shellcheck (уровень error), если он есть на машине
#   python   компиляция (синтаксис) каждого ci/**.py
#   guards   сторожа публичного репозитория: ci/guard-network.py (голая сеть вне retry.sh и net.py), ci/guard-parity.py (карта «шаг CI -> шаг precheck»),
#            ci/guard-test-vps.py (тестовый стенд без боевых ключей), ci/guard-releases.py (служебный релиз только предрелизом), ci/guard-test-version.py (формат версии теста x.y.z_test),
#            ci/guard-dispatch.py (запуск workflow только через ci/dispatch-wait.sh, у запускаемого вход caller в run-name)
# В конце печатается таблица времён шагов; любой упавший шаг даёт код 1, остальные шаги всё равно идут.
set -uo pipefail

cd "$(dirname "$0")/.."

failed=0
timings=()

step() {
    local name=$1 started=$SECONDS
    shift
    echo "== $name"
    if "$@"; then
        timings+=("$name $((SECONDS - started))s")
    else
        timings+=("$name $((SECONDS - started))s-FAILED")
        failed=1
    fi
}

shell_syntax() {
    local code=0 file
    while IFS= read -r file; do
        bash -n "$file" || { echo "::error file=$file::bash -n failed"; code=1; }
    done < <(find ci -name '*.sh' | sort)
    return "$code"
}

shell_lint() {
    if ! command -v shellcheck >/dev/null 2>&1; then
        echo "shellcheck is not installed here: skipped (the selfcheck workflow runs it)"
        return 0
    fi
    find ci -name '*.sh' -print0 | sort -z | xargs -0 shellcheck -S error
}

python_compile() {
    find ci -name '*.py' -print0 | sort -z | xargs -0 python3 -I -c '
import sys
bad = 0
for path in sys.argv[1:]:
    try:
        compile(open(path, encoding="utf-8").read(), path, "exec")
    except SyntaxError as error:
        print(f"::error file={path}::{error.msg} (line {error.lineno})")
        bad = 1
sys.exit(bad)
'
}

guards() {
    local code=0
    python3 -I ci/guard-network.py || code=1
    python3 -I ci/guard-parity.py || code=1
    python3 -I ci/guard-test-vps.py || code=1
    python3 -I ci/guard-releases.py || code=1
    python3 -I ci/guard-test-version.py || code=1
    python3 -I ci/guard-dispatch.py || code=1
    python3 -I ci/guard-edge.py || code=1
    return "$code"
}

netcall_errors() {
    local said
    said=$(bash -c 'set -euo pipefail; . ci/retry.sh; netcall once bash -c "echo refused >&2; exit 1"' 2>&1) && return 1
    [[ $said == *refused* ]] || { echo "netcall under set -e drops the error text of a failed call" >&2; return 1; }
}

python3 -c 'import yaml' 2>/dev/null || { echo "precheck: python3 needs the yaml module (pip install pyyaml)" >&2; exit 2; }

step syntax python3 -I ci/check-syntax.py
step shell-syntax shell_syntax
step shell-lint shell_lint
step python python_compile
step guards guards
step netcall netcall_errors

echo "== timings"
total=0
for row in "${timings[@]}"; do
    printf '   %-16s %s\n' "${row% *}" "${row##* }"
    seconds=${row##* }
    [[ $seconds =~ ^([0-9]+)s$ ]] && total=$((total + BASH_REMATCH[1]))
done
printf '   %-16s %ss\n' total "$total"

if ((failed)); then
    echo "precheck: RED" >&2
    exit 1
fi
echo "precheck: green"
