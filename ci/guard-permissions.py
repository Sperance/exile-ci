#!/usr/bin/env python3
"""Сторож прав вызывающего workflow: вызываемый workflow не может просить больше прав, чем даёт вызывающий.

    python3 -I ci/guard-permissions.py [корень репозитория]

Каждый job объявляет свои права (`permissions`), а прогон вызванного workflow идёт с токеном вызывающего: право,
которого у вызывающего нет, у вызванного не будет - шаг упадёт с 403. Сторож идёт по цепочкам запусков внутри
этого репозитория (`gh workflow run` и `ci/dispatch-wait.sh` с токеном прогона) и требует, чтобы каждый job
вызванного workflow получил права на запись, которые просит.

Красное - строкой ::error:: и код 1 (job guards в check-wip.yml, шаг «CI scripts guards» client.yml и server.yml; precheck).
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DISPATCH = re.compile(r"(?:gh\s+workflow\s+run|dispatch-wait\.sh)\s+([\w.-]+\.yml)\b")
WRITE = re.compile(r"write")
errors = []


def fail(message):
    errors.append(message)


def scopes(permissions):
    if not isinstance(permissions, dict):
        return None
    result = set()
    for key, value in permissions.items():
        if value == "write" or (key == "write-all"):
            result.add(key)
        elif key != "write-all" and value == "read":
            continue
    return result


def declared(job, workflow_permissions):
    own = job.get("permissions")
    if own is None:
        own = workflow_permissions
    if own == "write-all":
        return {"contents", "packages", "actions", "issues", "checks", "deployments", "discussions", "id-token", "pull-requests", "security-events", "statuses"}
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


def main():
    paths = {os.path.basename(path): path for path in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))}
    workflows = {name: load(path) for name, path in paths.items()}

    for name, jobs in workflows.items():
        for job, data in jobs.items():
            for target in sorted(data["dispatched"]):
                if target not in workflows:
                    fail(f"{name}: job {job} starts {target}, which does not exist")
                    continue
                given = data["scopes"]
                for other, target_data in workflows[target].items():
                    for scope in sorted(target_data["scopes"]):
                        if scope not in given:
                            fail(f"{name}: job {job} starts {target}, whose job {other} asks for {scope}: write, but the caller gives {sorted(given) or 'no write rights'}")
    if errors:
        for message in errors:
            print(f"::error::{message}")
        sys.exit(1)
    print("permissions guard: green (every called workflow gets the write rights it asks for)")


main()
