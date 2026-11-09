#!/usr/bin/env python3
"""Сводка времён Check wip и сторож замедления (job record в check-wip.yml): время каждого job и прогона, предупреждение, если прогон дольше 1,4 медианы.

    python3 -I ci/check-wip-timing.py <job'ы текущего прогона> <текущий прогон> <прошлые успешные прогоны>

Файлы делает job record через ci/retry.sh read gh api (токен github.token, право actions: read, только чтение): строки JSON `{name, started_at,
completed_at}` job'ов, объект прогона (`run_started_at`) и строки JSON `{id, run_started_at, updated_at}` последних успешных прогонов. Сети здесь нет.
В журнал и сводку идут имена job'ов и секунды: ни кода, ни данных. Предупреждение `::warning::` - не падение: код выхода всегда 0.
"""
import json
import os
import statistics
import sys
from datetime import datetime, timezone

FACTOR = 1.4
MINIMUM_RUNS = 3


def moment(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def json_lines(path):
    with open(path, encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def job_seconds(jobs):
    rows = []
    for job in jobs:
        if job.get("started_at") and job.get("completed_at"):
            rows.append((job["name"], int((moment(job["completed_at"]) - moment(job["started_at"])).total_seconds())))
    return sorted(rows, key=lambda row: -row[1])


def wall_seconds(run):
    return int((datetime.now(timezone.utc) - moment(run["run_started_at"])).total_seconds())


def previous_walls(runs):
    return [int((moment(run["updated_at"]) - moment(run["run_started_at"])).total_seconds()) for run in runs if run.get("updated_at") and run.get("run_started_at")]


def report(lines):
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")


def main():
    jobs_path, run_path, runs_path = sys.argv[1:4]
    rows = job_seconds(json_lines(jobs_path))
    with open(run_path, encoding="utf-8") as file:
        wall = wall_seconds(json.load(file))
    walls = previous_walls(json_lines(runs_path))
    lines = ["### Check wip timings (seconds)", "", "| job | seconds |", "|---|---|"]
    lines += [f"| {name} | {seconds} |" for name, seconds in rows]
    lines.append(f"| **run wall time** | **{wall}** |")
    if len(walls) >= MINIMUM_RUNS:
        median = int(statistics.median(walls))
        lines.append(f"| median of the last {len(walls)} successful runs | {median} |")
        report(lines)
        if wall > FACTOR * median:
            print(f"::warning::Check wip took {wall}s, more than {FACTOR}x the median {median}s of the last {len(walls)} successful runs: look for the slow job in the timing table of the run summary")
    else:
        lines.append(f"| median | not enough successful runs ({len(walls)}) |")
        report(lines)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"::warning::the Check wip timing summary failed: {type(error).__name__}")
    sys.exit(0)
