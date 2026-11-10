#!/usr/bin/env python3
"""Сторож релизов: служебный релиз CI (стенд, qa, арт, база, кэш Gradle) создаётся только предрелизом.

    python3 -I ci/guard-releases.py [корень репозитория]

Игра показывает игроку выпуски exile-ci не-предрелизы с тегом vX.Y.Z (раздел «Версия», отметка «Новое»); служебный релиз без --prerelease
попал бы в этот список. Каждая команда `gh release create` в .github/workflows/*.yml, .github/actions/*/action.yml (блоки run), ci/**/*.sh и ci/**/*.py
(строки с `\\` в конце склеиваются) обязана нести `--prerelease`; выпуск игрока - только с пометкой `# player-release` в строке над командой.
Пометка без команды под ней - тоже красное. Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml).
"""
import glob
import os
import re
import sys

import yaml

CREATE = re.compile(r"\bgh release create\b")
MARK = "# player-release"


def run_blocks(path):
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    blocks = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "run" and isinstance(value, str):
                    blocks.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return blocks


def commands(text):
    lines = text.splitlines()
    found, marked, index = [], False, 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == MARK:
            if marked:
                found.append((None, True))
            marked = True
            index += 1
            continue
        whole = line
        while whole.rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            whole = whole.rstrip()[:-1] + " " + lines[index].strip()
        if CREATE.search(whole) and not whole.lstrip().startswith("#"):
            found.append((whole, marked))
            marked = False
        elif marked and whole.strip():
            found.append((None, True))
            marked = False
        index += 1
    if marked:
        found.append((None, True))
    return found


def violations(text):
    found = []
    for command, marked in commands(text):
        if command is None:
            found.append(f"{MARK} without a gh release create right below it")
        elif not marked and "--prerelease" not in command:
            found.append(f"gh release create without --prerelease (a player release needs {MARK} above): {command.strip()[:120]}")
    return found


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    found = []
    for path in sorted(glob.glob(os.path.join(root, ".github/workflows/*.yml")) + glob.glob(os.path.join(root, ".github/actions/*/action.yml"))):
        for block in run_blocks(path):
            found += [(path, message) for message in violations(block)]
    for path in sorted(glob.glob(os.path.join(root, "ci/**/*.sh"), recursive=True) + glob.glob(os.path.join(root, "ci/**/*.py"), recursive=True)):
        if os.path.basename(path) == "guard-releases.py":
            continue
        with open(path, encoding="utf-8") as handle:
            found += [(path, message) for message in violations(handle.read())]
    for path, message in found:
        print(f"::error file={os.path.relpath(path, root)}::{message}")
    if not found:
        print("release guard: green")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
