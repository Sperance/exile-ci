#!/usr/bin/env python3
"""Сторож прав вызывающего workflow: вызываемый workflow не может просить больше прав, чем даёт вызывающий.

    python3 -I ci/guard-permissions.py [корень репозитория]

Два вида запусков workflow внутри этого репозитория, и права у них разные:

  - Вызов workflow (`uses: ./.github/workflows/<файл>.yml` в job): прогон вызванного workflow идёт с токеном вызывающего,
    и GitHub проверяет права статически, до запуска. Вызванный job не может просить право на запись, которого у вызывающего
    нет: workflow с таким вызовом не запускается вовсе ("Invalid workflow file ... is only allowed 'pages: none'"). Сторож
    требует, чтобы вызывающий дал вызванному все права на запись, которые вызванный просит (права вызванного job'а -
    пересечение прав вызывающего и его собственных).
  - Запуск workflow (`gh workflow run`, ci/dispatch-wait.sh): запущенный workflow идёт со своим токеном и берёт права из
    своего файла, а не от вызывающего (проверено на посте в Telegram: telegram.yml получил pages: write, хотя вызывающий
    клиент такого права не давал). Вызывающему нужно только право `actions: write` на сам запуск.

Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml; precheck).
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DISPATCH = re.compile(r"(?:gh\s+workflow\s+run|dispatch-wait\.sh)\s+([\w.-]+\.yml)\b")
REUSABLE = re.compile(r"^\./\.github/workflows/([\w.-]+\.yml)$")
WRITE_ALL = {
    "actions",
    "attestations",
    "checks",
    "contents",
    "deployments",
    "discussions",
    "id-token",
    "issues",
    "packages",
    "pages",
    "pull-requests",
    "security-events",
    "statuses",
}
errors = []


def fail(message):
    errors.append(message)


def scopes(permissions):
    if not isinstance(permissions, dict):
        return None
    result = set()
    for key, value in permissions.items():
        if value == "write" or key == "write-all":
            result.add(key)
        elif key != "write-all" and value == "read":
            continue
    return result


def declared(job, workflow_permissions):
    own = job.get("permissions")
    if own is None:
        own = workflow_permissions
    if own == "write-all":
        return set(WRITE_ALL)
    if own == "read-all" or own is None:
        return set()
    return scopes(own) or set()


def load(path):
    document = yaml.safe_load(open(path, encoding="utf-8")) or {}
    jobs = document.get("jobs") or {}
    workflow_permissions = document.get("permissions")
    result = {}
    for name, body in jobs.items():
        body = body or {}
        result[name] = {
            "scopes": declared(body, workflow_permissions),
            "dispatched": dispatched(body),
            "called": called(body),
        }
    return result


def dispatched(job):
    found = set()
    for step in job.get("steps") or []:
        run = step.get("run") if isinstance(step, dict) else None
        if not isinstance(run, str):
            continue
        for line in run.splitlines():
            if re.match(r"\s*#", line):
                continue
            if "GH_TOKEN=" in line and "github.token" not in line:
                continue
            found.update(DISPATCH.findall(line))
    return found


def called(job):
    uses = job.get("uses")
    if not isinstance(uses, str):
        return None
    match = REUSABLE.match(uses.strip())
    return match.group(1) if match else None


def required(target_jobs):
    result = set()
    for data in target_jobs.values():
        result |= data["scopes"]
    return result


def main():
    paths = {os.path.basename(path): path for path in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))}
    workflows = {name: load(path) for name, path in paths.items()}

    for name, jobs in workflows.items():
        for job, data in jobs.items():
            for target in sorted(data["dispatched"]):
                if target not in workflows:
                    fail(f"{name}: job {job} starts {target}, which does not exist")
                    continue
                if "actions" not in data["scopes"]:
                    fail(f"{name}: job {job} starts {target} and needs actions: write, but the caller gives {sorted(data['scopes']) or 'no write rights'}")
            target = data["called"]
            if target is None:
                continue
            if target not in workflows:
                fail(f"{name}: job {job} calls {target}, which does not exist")
                continue
            given = data["scopes"]
            for scope in sorted(required(workflows[target])):
                if scope not in given:
                    fail(f"{name}: job {job} calls {target}, whose jobs ask for {scope}: write, but the caller gives {sorted(given) or 'no write rights'}")
    if errors:
        for message in errors:
            print(f"::error::{message}")
        sys.exit(1)
    print("permissions guard: green (every called workflow gets the write rights it asks for)")


main()
