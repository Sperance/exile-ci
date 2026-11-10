#!/usr/bin/env python3
"""Тестовая сборка клиента (flavor qa, client.yml: changes, qa-apk, qa-release): номер версии и файлы предрелиза qa-<n>.

    python3 ci/qa-files.py version <последний тег v<x.y.z>> <число коммитов рабочей ветки> <sha7> <прошлая тестовая версия или -> <версия этой сборки, если уже опубликована, или -> [файл для name=]
        -> <последний боевой тег + k patch>_test, k - порядковый номер тестового обновления после тега (прошлая тестовая версия того же x.y и
           выше тега - её k + 1, иначе 1); повторный прогон той же сборки отдаёт прежнюю версию; строкой name=… в файл (по умолчанию stdout)
    python3 ci/qa-files.py plan <клон клиента> <от коммит или -> <до коммит> <файл>
        -> пункты «что проверить»: значения трейлеров `Test-Plan:` коммитов от..до (по строке на пункт, без повторов), в файл
    python3 ci/qa-files.py release <APK сборки> <versionName> <versionCode> <каталог результата> [файл пунктов plan [sha7]]
        -> ExileForge-qa.apk и update.json той же формы, что у релиза (ci/update_info.py), mandatory всегда true; sha7 - поле commit (номер сборки и
           коммит в строку версии не входят)

Заметки публичной тестовой сборки (и update.json, откуда их берёт приложение: другого источника у обновления нет) - только номер сборки и пункты
«что проверить»; раздел `## Следующая версия` RELEASE_NOTES.md в публичный предрелиз не попадает (будущие возможности до выхода не видны).
Содержимое кода в журнал не выводится. Ошибки - строкой ::error:: и код 1.
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notes
import update_info

APK_NAME = "ExileForge-qa.apk"
NOTES_TITLE = "Тестовая сборка"
PLAN_TITLE = "Что проверить:"
PLAN_TRAILER = re.compile(r"^Test-Plan:[ \t]*(.+?)[ \t]*$", re.M | re.I)
PLAN_ITEM_LIMIT = 200
PLAN_ITEMS_LIMIT = 30
SHA = re.compile(r"^[0-9a-f]{40}$")
TEST_SUFFIX = "_test"
RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
TEST_NAME = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:_test|-test\.\d+\+[0-9a-f]{7})$")
FALLBACK_COMMITS = 30


def release_parts(tag):
    found = RELEASE_TAG.match(tag)
    if not found:
        update_info.fail(f"released tag '{tag}' is not v<x.y.z>")
    return tuple(int(part) for part in found.groups())


def test_name(tag, previous):
    major, minor, patch = release_parts(tag)
    last = TEST_NAME.match(previous if previous != "-" else "")
    k = 1
    if last and (int(last.group(1)), int(last.group(2))) == (major, minor) and int(last.group(3)) > patch:
        k = int(last.group(3)) - patch + 1
    return f"{major}.{minor}.{patch + k}{TEST_SUFFIX}"


def version(tag, commits, sha7, previous, same, target):
    if not (commits.isdigit() and int(commits) > 0):
        update_info.fail(f"commit count '{commits}' is not a positive number")
    if len(sha7) != 7 or not all(c in "0123456789abcdef" for c in sha7):
        update_info.fail(f"short sha '{sha7}' is not 7 hex digits")
    name = same if TEST_NAME.match(same) and same.endswith(TEST_SUFFIX) else test_name(tag, previous)
    with open(target, "a", encoding="utf-8") as out:
        out.write(f"name={name}\n")


def plan(clone, old, new, target):
    if not SHA.match(new):
        update_info.fail(f"commit '{new}' is not a sha")
    span = [f"{old}..{new}"] if SHA.match(old) else [f"-{FALLBACK_COMMITS}", new]
    done = subprocess.run(["git", "-C", clone, "log", "--format=%B%x00", *span], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        update_info.fail("the commits of the test build could not be read")
    items = []
    for message in done.stdout.split("\0"):
        for raw in PLAN_TRAILER.findall(message):
            item = " ".join(raw.split())[:PLAN_ITEM_LIMIT]
            if item and item not in items and len(items) < PLAN_ITEMS_LIMIT:
                items.append(item)
    with open(target, "w", encoding="utf-8") as out:
        out.write("\n".join(items) + ("\n" if items else ""))
    print(f"test plan: {len(items)} item(s)")


def notes_of(name, plan_file):
    items = [line.strip() for line in open(plan_file, encoding="utf-8").read().splitlines() if line.strip()] if plan_file else []
    lines = [f"{NOTES_TITLE} {name}"]
    if items:
        lines += ["", PLAN_TITLE, *[f"- {item}" for item in items]]
    return "\n".join(lines)


def release(apk_source, name, code, out, plan_file=None, commit=None):
    if not code.isdigit():
        update_info.fail(f"versionCode '{code}' is not a number")
    os.makedirs(out, exist_ok=True)
    shutil.copyfile(apk_source, os.path.join(out, APK_NAME))
    update_info.write(out, int(code), name, APK_NAME, notes_of(name, plan_file), True, commit)


def main():
    command, args = sys.argv[1], sys.argv[2:]
    if command == "version" and len(args) in (5, 6):
        version(*args[:5], args[5] if len(args) == 6 else "/dev/stdout")
    elif command == "plan" and len(args) == 4:
        plan(*args)
    elif command == "release" and len(args) in (4, 5, 6):
        release(*args)
    else:
        update_info.fail("usage: qa-files.py version <tag> <commits> <sha7> <previous|-> <same|-> [file] | plan <clone> <from|-> <to> <file> | release <apk> <name> <code> <dir> [plan file [sha7]]")


main()
