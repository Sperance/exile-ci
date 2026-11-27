#!/usr/bin/env python3
"""Номер выпуска в исходниках клиента: versionCode/versionName в app/build.gradle.kts и заголовок заметок в RELEASE_NOTES.md.

Следующая версия считается от последнего выпущенного тега v<x.y.z> в exile-ci: patch - x.y.z+1, minor - x.y+1.0.
versionCode - текущий в app/build.gradle.kts плюс один. Раздел `## Следующая версия` переименовывается в `## <versionName>`;
нет раздела, он пуст или подразделы нарушают порядок «Новое, Изменения, Исправления, Техническое» (ci/notes.py) - ошибка; пустые
подразделы при переименовании убираются. Содержимое заметок и кода в журнал не выводится: только номер версии и кода.
Использование: ci/bump-release.py <каталог исходников клиента> <patch|minor> <последний тег, например v0.24.2> [файл для version= и code=]
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notes

NEXT_HEADING = notes.NEXT_HEADING


def next_version(tag: str, bump: str) -> str:
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    if not match:
        sys.exit(f"::error::last release tag '{tag}' is not v<major>.<minor>.<patch>")
    major, minor, patch = map(int, match.groups())
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"::error::unknown bump '{bump}'")


def bump_gradle(path: str, version: str) -> int:
    text = open(path, encoding="utf-8").read()
    code_match = re.search(r"(versionCode\s*=\s*)(\d+)", text)
    if not code_match or not re.search(r'versionName\s*=\s*"[^"]*"', text):
        sys.exit("::error::versionCode/versionName not found in app/build.gradle.kts")
    code = int(code_match.group(2)) + 1
    text = text.replace(code_match.group(0), f"{code_match.group(1)}{code}", 1)
    text = re.sub(r'(versionName\s*=\s*)"[^"]*"', lambda m: f'{m.group(1)}"{version}"', text, count=1)
    open(path, "w", encoding="utf-8").write(text)
    return code


def rename_notes(path: str, version: str) -> None:
    lines = open(path, encoding="utf-8").read().split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == NEXT_HEADING]
    if len(starts) != 1:
        sys.exit(f"::error::RELEASE_NOTES.md must have exactly one '{NEXT_HEADING}' section, found {len(starts)}")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    if not any(line.strip() for line in lines[start + 1:end]):
        sys.exit(f"::error::the '{NEXT_HEADING}' section of RELEASE_NOTES.md is empty")
    broken = notes.problems("\n".join(lines[start + 1:end]))
    if broken:
        sys.exit(f"::error::the '{NEXT_HEADING}' section of RELEASE_NOTES.md: {'; '.join(broken)}")
    lines[start] = f"## {version}"
    lines[start + 1:end] = notes.rewrite_without_empty("\n".join(lines[start + 1:end])).split("\n")
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def check_notes(src: str, heading: str) -> None:
    """Структура заметок - тем же скриптом, что и локально в precheck клиента: один раздел, подразделы по порядку.

    Раньше здесь проверялся только раздел «## Следующая версия», а весь файл - только в конце релиза: мелочь (например, забытый
    раздел прошлой версии) падала через тринадцать минут сборки. Теперь это первая минута прогона.
    """
    script = os.path.join(src, "scripts", "check-release-notes.py")
    if not os.path.exists(script):
        sys.exit(f"::error::{script} is missing: the release notes check belongs to the client")
    check = subprocess.run([sys.executable, script, os.path.join(src, "RELEASE_NOTES.md"), heading], capture_output=True, text=True)
    if check.returncode != 0:
        sys.exit((check.stdout + check.stderr).strip())


def main() -> None:
    src, bump, tag = sys.argv[1:4]
    version = next_version(tag, bump)
    code = bump_gradle(f"{src}/app/build.gradle.kts", version)
    rename_notes(f"{src}/RELEASE_NOTES.md", version)
    check_notes(src, f"## {version}")
    print(f"version {version}, code {code}")
    with open(sys.argv[4] if len(sys.argv) > 4 else "/dev/null", "a", encoding="utf-8") as out:
        out.write(f"version={version}\ncode={code}\n")


if __name__ == "__main__":
    main()
