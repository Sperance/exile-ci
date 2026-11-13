#!/usr/bin/env python3
"""Сторож утилит age: CI ставит age из выпуска на GitHub (ci/crypt.sh, ensure_age), и ставятся только утилиты из AGE_TOOLS.
Утилита, что зовётся в блоках run workflow или в ci/*.sh, но не ставится, на раннере отсутствует: вызов молча пуст
(так doctor считал SEAL_AGE_RECIPIENT не совпавшим с SEAL_AGE_IDENTITY, хотя ключи были верны).

    python3 -I ci/guard-age.py [корень репозитория]

Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml; precheck).
"""
import glob
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TOOL = re.compile(r"(?<![\w./-])(age-keygen|age-plugin-[\w-]+|age)(?=\s)")
CRYPT = os.path.join(ROOT, "ci", "crypt.sh")


def installed():
    text = open(CRYPT, encoding="utf-8").read()
    found = re.search(r'^AGE_TOOLS="([^"]*)"', text, re.M)
    return set(found.group(1).split()) if found else set()


def code(line):
    stripped = line.lstrip()
    return "" if stripped.startswith("#") else line.split(" #", 1)[0]


def main():
    tools = installed()
    errors = []
    if "age" not in tools:
        errors.append("ci/crypt.sh: AGE_TOOLS не содержит age")
    files = glob.glob(os.path.join(ROOT, ".github", "**", "*.yml"), recursive=True) + glob.glob(os.path.join(ROOT, "ci", "*.sh"))
    for path in sorted(files):
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                for match in TOOL.finditer(code(line)):
                    if match.group(1) not in tools:
                        errors.append(f"{os.path.relpath(path, ROOT)}:{number}: {match.group(1)} зовётся, но ensure_age её не ставит (AGE_TOOLS в ci/crypt.sh)")
    errors = list(dict.fromkeys(errors))
    for error in errors:
        print(f"::error::{error}")
    if errors:
        sys.exit(1)
    print(f"guard-age: ok ({len(files)} files)")


main()
