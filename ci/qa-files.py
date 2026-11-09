#!/usr/bin/env python3
"""Тестовая сборка клиента (flavor qa, client.yml: changes, qa-apk, qa-release): номер версии и файлы предрелиза qa-<n>.

    python3 ci/qa-files.py version <последний тег v<x.y.z>> <число коммитов рабочей ветки> <sha7> [файл для name=]
        -> <следующий patch>-test.<число коммитов>+<sha7>, строкой name=… в файл (по умолчанию stdout)
    python3 ci/qa-files.py release <APK сборки> <versionName> <versionCode> <каталог результата>   (из каталога исходников клиента)
        -> ExileForge-qa.apk и update.json той же формы, что у релиза (ci/update_info.py), mandatory всегда true

Заметки - раздел `## Следующая версия` RELEASE_NOTES.md как есть (то, что уйдёт в выпуск); нет раздела - короткая строка.
Содержимое заметок и кода в журнал не выводится. Ошибки - строкой ::error:: и код 1.
"""
import importlib.util
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notes
import update_info

APK_NAME = "ExileForge-qa.apk"
NO_NOTES = "Тестовая сборка"


def release_version(tag):
    spec = importlib.util.spec_from_file_location("bump_release", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bump-release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.next_version(tag, "patch")


def version(tag, commits, sha7, target):
    if not (commits.isdigit() and int(commits) > 0):
        update_info.fail(f"commit count '{commits}' is not a positive number")
    if len(sha7) != 7 or not all(c in "0123456789abcdef" for c in sha7):
        update_info.fail(f"short sha '{sha7}' is not 7 hex digits")
    name = f"{release_version(tag)}-test.{commits}+{sha7}"
    with open(target, "a", encoding="utf-8") as out:
        out.write(f"name={name}\n")


def release(apk_source, name, code, out):
    if not code.isdigit():
        update_info.fail(f"versionCode '{code}' is not a number")
    os.makedirs(out, exist_ok=True)
    shutil.copyfile(apk_source, os.path.join(out, APK_NAME))
    section = notes.next_section(open("RELEASE_NOTES.md", encoding="utf-8").read())
    update_info.write(out, int(code), name, APK_NAME, (section or "").strip() or NO_NOTES, True)


def main():
    command, args = sys.argv[1], sys.argv[2:]
    if command == "version" and len(args) in (3, 4):
        version(*args[:3], args[3] if len(args) == 4 else "/dev/stdout")
    elif command == "release" and len(args) == 4:
        release(*args)
    else:
        update_info.fail("usage: qa-files.py version <tag> <commits> <sha7> [file] | release <apk> <name> <code> <dir>")


main()
