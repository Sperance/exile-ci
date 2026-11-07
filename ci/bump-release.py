#!/usr/bin/env python3
"""Номер выпуска в исходниках клиента: versionCode/versionName в app/build.gradle.kts и заголовок заметок в RELEASE_NOTES.md.

Следующая версия считается от последнего выпущенного тега v<x.y.z> в exile-ci: patch - x.y.z+1, minor - x.y+1.0.
versionCode - текущий в app/build.gradle.kts плюс один. Раздел `## Следующая версия` переименовывается в `## <versionName>`;
нет раздела или он пуст - ошибка. Содержимое заметок и кода в журнал не выводится: только номер версии и кода.
Использование: ci/bump-release.py <каталог исходников клиента> <patch|minor> <последний тег, например v0.24.2> [файл для version= и code=]
"""
import re
import sys

NEXT_HEADING = "## Следующая версия"


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
    lines[start] = f"## {version}"
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def main() -> None:
    src, bump, tag = sys.argv[1:4]
    version = next_version(tag, bump)
    code = bump_gradle(f"{src}/app/build.gradle.kts", version)
    rename_notes(f"{src}/RELEASE_NOTES.md", version)
    print(f"version {version}, code {code}")
    with open(sys.argv[4] if len(sys.argv) > 4 else "/dev/null", "a", encoding="utf-8") as out:
        out.write(f"version={version}\ncode={code}\n")


main()
