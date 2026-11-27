#!/usr/bin/env python3
"""Сторож расписания: задача магазинов не должна зависеть от одной cron-строки.

    python3 -I ci/guard-schedule.py [каталог репозитория]

Проблема, которую он ловит: задача `store-status` (опрос магазинов и повтор выкладки) была привязана к
cron-строке в условии запуска. Планировщик GitHub сдвигает и пропускает тики расписания, и такая привязка
теряла задачу молча: версия, ждавшая модерации прошлой, так и не уходила в магазин (часы, а не минуты).
Поэтому условие задачи магазинов - любое событие расписания, без сверки cron-строки.

Красное: условие задачи магазинов фильтрует по `github.event.schedule`, либо в расписании workflow'а
есть cron, которому не отвечает ни одна задача.
"""
import os
import re
import sys

import yaml

WORKFLOW = os.path.join(".github", "workflows", "maintenance.yml")
STORE_JOB = "store-status"


def crons(text):
    return re.findall(r"-\s*cron:\s*'([^']+)'", text) or re.findall(r"-\s*cron:\s*\"([^\"]+)\"", text)


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    path = os.path.join(root, WORKFLOW)
    if not os.path.exists(path):
        print(f"::notice::{WORKFLOW} is not here: the schedule guard is skipped")
        return
    text = open(path, encoding="utf-8").read()
    document = yaml.safe_load(text)
    schedule = (document.get(True) or document.get("on") or {}).get("schedule") or []
    problems = []
    jobs = document.get("jobs") or {}
    store = jobs.get(STORE_JOB)
    if store is None:
        problems.append(f"the workflow has no `{STORE_JOB}` job")
    else:
        condition = str(store.get("if") or "")
        if "github.event_name == 'schedule'" not in condition:
            problems.append(f"the `{STORE_JOB}` job does not run on the schedule: {condition}")
        if "github.event.schedule" in condition:
            problems.append(f"the `{STORE_JOB}` job is tied to one cron string: {condition}")
    known = {str((job.get("if") or "")) for job in jobs.values()}
    any_schedule = [condition for condition in known if "github.event_name == 'schedule'" in condition and "github.event.schedule" not in condition]
    for entry in schedule:
        cron = entry.get("cron") if isinstance(entry, dict) else entry
        if not cron:
            continue
        if any(cron in condition for condition in known) or any_schedule:
            continue
        problems.append(f"the cron `{cron}` starts no task of this workflow")
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        sys.exit(1)
    print(f"schedule guard: green ({len(schedule)} cron(s), the store status runs on every tick)")


if __name__ == "__main__":
    main()
