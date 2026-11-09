#!/usr/bin/env python3
"""Сторож паритета «CI и precheck»: каждый job и шаг server.yml, client.yml, check-wip.yml имеет решение в ci/precheck-map.txt.

    python3 -I ci/guard-parity.py [--list] [--client-precheck файл] [--server-precheck файл] [корень репозитория]

Карта - строки `ключ => цель`:
  ключ    `<workflow>/<job>` или `<workflow>/<job>/<имя шага>` (шаг без имени: `uses:<действие>`; шаг с run обязан иметь имя);
          workflow - server, client, check-wip; `*` в ключе - любая последовательность знаков.
  цель    `precheck:<client|server>:<шаг>[,<шаг>...]` - этот шаг CI проверяет и scripts/precheck.sh (шаги: `echo "== имя"`, `gradle_step имя`, `run_step имя`)
          или `ci-only: <причина>` - локально не повторить (эмулятор, образ, сборки R8, браузер, секреты, деплой), причина от 10 знаков.
Красное: шаг или job без строки (новый шаг без решения); строка без шага (устарела); подстановка `*` у цели precheck; шаг precheck из карты не найден в
переданном файле precheck.sh (файлы клиента и сервера job guards check-wip достаёт из обоих репозиториев; в других job'ах проверка пропускается).
Что гоняет precheck и чего нет - rules-md/process/ci.md клиента и rules-md/server/ci.md сервера.
"""
import fnmatch
import os
import re
import sys

import yaml

WORKFLOWS = ("server", "client", "check-wip")
STEP_IN_PRECHECK = re.compile(r'(?:gradle_step|run_step|echo "==) ([\w-]+)')


def keys_of(root):
    keys = []
    for workflow in WORKFLOWS:
        document = yaml.safe_load(open(os.path.join(root, ".github", "workflows", f"{workflow}.yml"), encoding="utf-8"))
        for job, body in document["jobs"].items():
            keys.append(f"{workflow}/{job}")
            for step in body.get("steps") or []:
                if step.get("name"):
                    keys.append(f"{workflow}/{job}/{step['name']}")
                elif "uses" in step:
                    keys.append(f"{workflow}/{job}/uses:{step['uses'].split('@')[0]}")
                else:
                    keys.append(f"{workflow}/{job}/<unnamed run step: give it a name>")
    return keys


def load_map(root):
    rules, problems = [], []
    path = os.path.join(root, "ci", "precheck-map.txt")
    for number, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if " => " not in raw:
            problems.append(f"ci/precheck-map.txt:{number}: expected `key => target`")
            continue
        key, target = (part.strip() for part in raw.split(" => ", 1))
        if target.startswith("ci-only:"):
            if len(target[len("ci-only:"):].strip()) < 10:
                problems.append(f"ci/precheck-map.txt:{number}: ci-only needs a reason of at least 10 characters")
        elif re.fullmatch(r"precheck:(client|server):[\w-]+(,[\w-]+)*", target):
            if "*" in key:
                problems.append(f"ci/precheck-map.txt:{number}: a wildcard key cannot map to a precheck step: name the step")
        else:
            problems.append(f"ci/precheck-map.txt:{number}: the target is `precheck:<client|server>:<step>[,<step>]` or `ci-only: <reason>`")
            continue
        rules.append((number, key, target))
    return rules, problems


def precheck_steps(path):
    return set(STEP_IN_PRECHECK.findall(open(path, encoding="utf-8").read()))


def main():
    arguments = sys.argv[1:]
    listing = "--list" in arguments
    files = {}
    rest = []
    iterator = iter([a for a in arguments if a != "--list"])
    for argument in iterator:
        if argument in ("--client-precheck", "--server-precheck"):
            files[argument[2:].split("-")[0]] = next(iterator)
        else:
            rest.append(argument)
    root = os.path.abspath(rest[0]) if rest else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    keys = keys_of(root)
    if listing:
        print("\n".join(keys))
        return
    rules, problems = load_map(root)
    used = set()
    for key in keys:
        hits = [i for i, (_, pattern, _) in enumerate(rules) if fnmatch.fnmatchcase(key, pattern.replace("[", "[[]"))]
        if not hits:
            problems.append(f"{key}: no decision in ci/precheck-map.txt (precheck step or `ci-only: reason`)")
        used.update(hits)
    for i, (number, pattern, _) in enumerate(rules):
        if i not in used:
            problems.append(f"ci/precheck-map.txt:{number}: `{pattern}` matches no job or step: remove or rename it")
    available = {name: precheck_steps(path) for name, path in files.items()}
    for number, pattern, target in rules:
        if target.startswith("precheck:"):
            _, repo, steps = target.split(":")
            for step in steps.split(","):
                if repo in available and step not in available[repo]:
                    problems.append(f"ci/precheck-map.txt:{number}: the {repo} scripts/precheck.sh has no step `{step}`")
    for problem in problems:
        print(f"::error::{problem}")
    mapped = sum(1 for _, _, t in rules if t.startswith("precheck:"))
    print(f"parity guard: {'RED, ' + str(len(problems)) + ' problem(s)' if problems else 'green'} ({len(keys)} jobs and steps, {mapped} mapped to precheck, "
          f"{len(rules) - mapped} ci-only{', precheck files checked: ' + ', '.join(sorted(files)) if files else ', precheck files not given'})")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
