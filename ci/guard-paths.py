#!/usr/bin/env python3
"""Сторож путей к скриптам этого репозитория: шаг workflow работает в своём каталоге, а путь к файлу считается от него.

    python3 -I ci/guard-paths.py [корень репозитория]

1. Ссылка на файл этого репозитория (путь с `ci/`) из шага не должна вести за пределы репозитория: шаг без
   `working-directory` работает в корне, и `../ci/...` оттуда - уже снаружи (шаг падает с кодом 127).
2. Ссылка на `ci/...` изнутри репозитория должна указывать на существующий файл.

Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml; precheck).
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REFERENCE = re.compile(r"(?<![\w/])((?:\.\./)*ci/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)")
errors = []


def fail(message):
    errors.append(message)


def code_lines(text):
    for line in text.splitlines():
        if not re.match(r"\s*#", line):
            yield line


def working_directory(body, step):
    for value in (step.get("working-directory"), ((body.get("defaults") or {}).get("run") or {}).get("working-directory")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def steps_of(path):
    document = yaml.safe_load(open(path, encoding="utf-8")) or {}
    for name, body in (document.get("jobs") or {}).items():
        for step in (body or {}).get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield name, step.get("name") or step.get("id") or "step", working_directory(body, step), step["run"]


def main():
    for path in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        relative = os.path.relpath(path, ROOT)
        for job, name, directory, block in steps_of(path):
            for line in code_lines(block):
                for reference in REFERENCE.findall(line):
                    target = os.path.normpath(os.path.join(directory, reference))
                    if target.startswith(".."):
                        fail(f"{relative}: job {job}, step '{name}': '{reference}' leaves the repository (working directory '{directory or 'the root'}')")
                    elif not os.path.isfile(os.path.join(ROOT, target)):
                        fail(f"{relative}: job {job}, step '{name}': '{reference}' does not exist (working directory '{directory or 'the root'}')")
    if errors:
        for message in errors:
            print(f"::error::{message}")
        sys.exit(1)
    print("paths guard: green (every reference to a script of this repository leads to an existing file)")


main()
