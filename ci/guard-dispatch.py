#!/usr/bin/env python3
"""Сторож запуска workflow: запуск без ожидания («выстрелил и забыл») прячет красные прогоны, поэтому workflow запускают только через ci/dispatch-wait.sh.

    python3 -I ci/guard-dispatch.py [корень репозитория]

1. Голый `gh workflow run` вне ci/dispatch-wait.sh (в блоках run workflow и composite-действий, в ci/**/*.sh и *.py; комментарии не в счёт) - красное.
2. Каждый workflow, что запускается через `dispatch-wait.sh <файл>.yml`, объявляет вход `caller` в workflow_dispatch и держит `inputs.caller` в run-name:
   по этой метке в display_title helper находит свой прогон; без неё он не найдёт его и упадёт через 10 минут.
Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml; precheck).
"""
import glob
import os
import re
import sys

import yaml

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BARE = re.compile(r"""gh\s+workflow\s+run\b|["']gh["']\s*,\s*["']workflow["']\s*,\s*["']run["']""")
CALL = re.compile(r"dispatch-wait\.sh\s+([\w.-]+\.yml)\b")
HELPER = os.path.join("ci", "dispatch-wait.sh")
errors = []


def fail(message):
    errors.append(message)


def code_lines(text):
    for line in text.splitlines():
        if not re.match(r"\s*#", line):
            yield line


def run_blocks(path):
    document = yaml.safe_load(open(path, encoding="utf-8")) or {}
    jobs = (document.get("jobs") or {}).values() if "jobs" in document else [document.get("runs") or {}]
    for body in jobs:
        for step in (body or {}).get("steps") or []:
            if isinstance(step.get("run"), str):
                yield step["run"]


def scan():
    called = set()
    workflows = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
    actions = sorted(glob.glob(os.path.join(ROOT, ".github", "actions", "*", "action.yml")))
    for path in workflows + actions:
        for block in run_blocks(path):
            for line in code_lines(block):
                if BARE.search(line):
                    fail(f"{os.path.relpath(path, ROOT)}: a bare 'gh workflow run' ('{line.strip()[:80]}'): start workflows with ci/dispatch-wait.sh so the caller waits and fails with the run")
                called.update(CALL.findall(line))
    for path in sorted(glob.glob(os.path.join(ROOT, "ci", "**", "*"), recursive=True)):
        relative = os.path.relpath(path, ROOT)
        if relative == HELPER or not path.endswith((".sh", ".py")) or os.path.basename(path).startswith("guard-"):
            continue
        for line in code_lines(open(path, encoding="utf-8").read()):
            if BARE.search(line):
                fail(f"{relative}: a bare 'gh workflow run': start workflows with ci/dispatch-wait.sh")
            called.update(CALL.findall(line))
    return called


def check_dispatched(name):
    path = os.path.join(ROOT, ".github", "workflows", name)
    if not os.path.isfile(path):
        fail(f"dispatch-wait.sh starts {name}, which does not exist")
        return
    document = yaml.safe_load(open(path, encoding="utf-8"))
    triggers = document.get(True) or document.get("on") or {}
    dispatch = triggers.get("workflow_dispatch") if isinstance(triggers, dict) else None
    inputs = (dispatch or {}).get("inputs") or {}
    if "caller" not in inputs:
        fail(f"{name} is started by dispatch-wait.sh but has no workflow_dispatch input 'caller'")
    if "inputs.caller" not in str(document.get("run-name", "")):
        fail(f"{name} is started by dispatch-wait.sh but its run-name does not carry inputs.caller")


def main():
    called = scan()
    for name in sorted(called):
        check_dispatched(name)
    if errors:
        for message in errors:
            print(f"::error::{message}")
        sys.exit(1)
    print(f"dispatch guard: green ({len(called)} dispatched workflows wait and carry the caller marker)")


main()
