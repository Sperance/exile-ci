#!/usr/bin/env python3
"""Файлы релиза клиента (job `release` client.yml): APK, карта R8, заметки и update.json - то, что читает обновлятор игры
(Updates.kt): сборка, провод, правила и форма контента, на которых она говорит, APK и его SHA-256.

Запуск из каталога исходников клиента (src/) после распаковки сборки release-apk; в окружении DIRECT_APK и DIRECT_MAPPING
(`. ci/build-tasks.env`):
    python3 ../ci/release-files.py <тег v<versionName>> <каталог результата>
В каталог результата кладутся ExileForge-<тег>.apk, mapping.txt, RELEASE_NOTES.md и update.json. Ошибки - строкой ::error:: и код 1.
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notes as release_notes
import update_info
from update_info import fail, first_group

# Пути результата сборки прямого канала - из ci/build-tasks.env (workflow кладёт их в окружение как DIRECT_APK и DIRECT_MAPPING)
APK_SOURCE = os.environ["DIRECT_APK"]
MAPPING_SOURCE = os.environ["DIRECT_MAPPING"]


def main():
    tag, out = sys.argv[1], sys.argv[2]
    name = tag.removeprefix("v")
    apk = f"ExileForge-{tag}.apk"
    shutil.copyfile(APK_SOURCE, os.path.join(out, apk))
    shutil.copyfile(MAPPING_SOURCE, os.path.join(out, "mapping.txt"))

    # Заметки: в RELEASE_NOTES.md - только эта версия, под первым заголовком «## <versionName>», подразделы по ci/notes.py; в update.json
    # (его читает игра, Updates.kt / WhatsNew) они уходят целиком, разделы разбирает игра.
    heading = next((line.rstrip(" \t\r\n\f\v") for line in open("RELEASE_NOTES.md", encoding="utf-8") if line.startswith("## ")), "")
    if heading != f"## {name}":
        fail(f"RELEASE_NOTES.md first heading is '{heading}', not '## {name}'")
    broken = release_notes.problems(open("RELEASE_NOTES.md", encoding="utf-8").read().split("\n", 1)[1])
    if broken:
        fail(f"RELEASE_NOTES.md: {'; '.join(broken)}")
    shutil.copyfile("RELEASE_NOTES.md", os.path.join(out, "RELEASE_NOTES.md"))

    code = first_group("app/build.gradle.kts", r"versionCode = ([0-9]*)")
    if not code:
        fail("update.json: versionCode not found")

    # Обязательность релиза: трейлер «Update-Mandatory: yes» в сообщении коммита релиза делает сборку обязательной и на том же
    # проводе; без него релиз на том же проводе - мягкое обновление (тост, не диалог).
    message = subprocess.run(["git", "log", "-1", "--format=%B"], check=True, capture_output=True, text=True).stdout
    mandatory = re.search(r"^Update-Mandatory: yes", message, re.IGNORECASE | re.MULTILINE) is not None

    notes = open("RELEASE_NOTES.md", encoding="utf-8").read().split("\n", 1)[1].strip()
    update_info.write(out, int(code), name, apk, notes, mandatory)


main()
