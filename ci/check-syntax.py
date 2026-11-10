#!/usr/bin/env python3
"""Синтаксис workflow и действий exile-ci (ci/precheck.sh): YAML каждого файла .github/**.yml разбирается, каждый блок `run:` проходит `bash -n`.

    python3 -I ci/check-syntax.py [корень репозитория]

Выражения `${{ ... }}` перед проверкой заменяются заглушкой: Actions подставляет их до запуска bash. Блоки с `shell:`, отличным от bash, пропускаются.
В вывод идут только пути и имена шагов; ничего секретного файлы не содержат (репозиторий публичный).
"""
import glob
import os
import re
import subprocess
import sys

import yaml

EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)
RUNNER = re.compile(r"\brunner\.")


def run_blocks(document):
    jobs = (document.get("jobs") or {}) if "jobs" in document else {"action": document.get("runs") or {}}
    for job, body in jobs.items():
        for index, step in enumerate(body.get("steps") or []):
            if isinstance(step.get("run"), str) and step.get("shell", "bash") in ("bash", "bash -e {0}"):
                yield f"{job}/{step.get('name') or f'step {index + 1}'}", step["run"]


def runner_in_job_env(document):
    scopes = {"workflow": document.get("env") or {}}
    scopes.update({job: body.get("env") or {} for job, body in (document.get("jobs") or {}).items() if isinstance(body, dict)})
    for scope, env in scopes.items():
        for name, value in env.items() if isinstance(env, dict) else []:
            if any(RUNNER.search(expression) for expression in EXPRESSION.findall(str(value))):
                yield f"{scope}/env.{name}"


def main():
    root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = sorted(glob.glob(os.path.join(root, ".github", "**", "*.yml"), recursive=True))
    problems = 0
    blocks = 0
    for path in paths:
        relative = os.path.relpath(path, root)
        try:
            with open(path, encoding="utf-8") as file:
                document = yaml.safe_load(file)
        except yaml.YAMLError as error:
            print(f"::error file={relative}::YAML does not parse: {str(error).splitlines()[0]}")
            problems += 1
            continue
        for label in runner_in_job_env(document):
            print(f"::error file={relative}::{label}: the runner context is not available in env above the steps, the workflow would not start; set it on the step")
            problems += 1
        for label, script in run_blocks(document):
            blocks += 1
            result = subprocess.run(["bash", "-n"], input=EXPRESSION.sub("EXPR", script), capture_output=True, text=True, check=False)
            if result.returncode != 0:
                print(f"::error file={relative}::{label}: bash -n failed: {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'syntax error'}")
                problems += 1
    print(f"syntax: {len(paths)} YAML files, {blocks} run blocks, {problems} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
