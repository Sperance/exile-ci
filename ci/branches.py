#!/usr/bin/env python3
"""Чистка влитых черновиков пакетов wip-<id> (.github/workflows/maintenance.yml, задача branches) в ExileForge, ktor-bestgame и exile-ci.

Имя черновика - строго ^wip-[a-z0-9-]+$: `wip`, `main` и рабочие ветки не трогаются никогда, в том числе с force.
Без force черновик удаляется, только когда все его коммиты вошли в `wip` или в ветку по умолчанию репозитория: `git cherry <ветка> <черновик>`
не оставляет «+» (коммит либо содержится в ветке, либо совпадает с чужим по patch-id - координатор вливает пакеты cherry-pick'ом, sha другие).
Читает голый клон веток (приватные - токеном SOURCE_TOKEN, exile-ci - GITHUB_TOKEN), удаляет REST DELETE /git/refs/heads/<ветка>:
EXILEFORGE_TOKEN для ExileForge и ktor-bestgame (нужен Contents: write), GITHUB_TOKEN для exile-ci. Нет токена или 403/404 - предупреждение
со счётчиком, остальные репозитории идут дальше.

Окружение: DRAFTS - пары `репозиторий:ветка` через пробел (пусто - все wip-* трёх репозиториев), FORCE=true - без проверки влития
(только с явным DRAFTS), SOURCE_TOKEN, EXILEFORGE_TOKEN, GITHUB_TOKEN, GITHUB_STEP_SUMMARY.
В публичный журнал - только счётчики: имена веток приватных репозиториев не выводятся.
Использование: ci/branches.py
"""
import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.error

from store_common import fail, say
import net

API = "https://api.github.com"
OWNER = "Sperance"
REPOS = ("ExileForge", "ktor-bestgame", "exile-ci")
PRIVATE = ("ExileForge", "ktor-bestgame")
DRAFT = re.compile(r"^wip-[a-z0-9-]+$")
UPSTREAM = "wip"


def read_token(repo):
    return os.environ.get("GITHUB_TOKEN" if repo not in PRIVATE else "SOURCE_TOKEN", "").strip()


def delete_token(repo):
    return os.environ.get("GITHUB_TOKEN" if repo not in PRIVATE else "EXILEFORGE_TOKEN", "").strip()


def api(method, path, token):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        response = net.fetch(API + path, method=method, headers=headers, timeout=30)
        return response.status, json.loads(response.body) if response.body else None
    except urllib.error.HTTPError as error:
        return error.code, None


def git(directory, *args):
    return subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True)


def mirror(repo, token, directory):
    """Голый клон всех веток репозитория; токен - заголовком одной команды, в конфиг клона не попадает."""
    subprocess.run(["git", "init", "--bare", "--quiet", directory], check=True, capture_output=True)
    url = f"https://github.com/{OWNER}/{repo}.git"
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    done = net.run("read", ["git", "-C", directory, "-c", f"http.extraheader=AUTHORIZATION: basic {auth}", "fetch", "--quiet", "--no-tags", url, "+refs/heads/*:refs/heads/*"], capture_output=True, text=True)
    return done.returncode == 0


def integrated(directory, draft, upstreams):
    """Каждый коммит черновика есть в какой-то из веток (содержится или совпадает по patch-id): часть пакета могла уйти в wip, часть - в основную
    ветку, поэтому «+» считается по пересечению ответов `git cherry` всех веток; пустой остаток - влито. Ошибка git - не влито."""
    left = None
    for upstream in upstreams:
        out = git(directory, "cherry", upstream, draft)
        if out.returncode != 0:
            return False
        plus = {line.split()[1] for line in out.stdout.splitlines() if line.startswith("+")}
        left = plus if left is None else left & plus
    return not left


def parse_drafts(text):
    pairs = []
    for item in text.split():
        repo, _, branch = item.partition(":")
        if repo not in REPOS or not branch:
            fail("drafts: an item is not <ExileForge|ktor-bestgame|exile-ci>:<branch>")
        pairs.append((repo, branch))
    return pairs


def main():
    force = os.environ.get("FORCE", "").strip().lower() == "true"
    explicit = parse_drafts(os.environ.get("DRAFTS", ""))
    if force and not explicit:
        fail("force needs an explicit drafts list")
    counts = {repo: {"deleted": 0, "kept": 0, "refused": 0} for repo in REPOS}
    for repo in REPOS:
        wanted = [branch for r, branch in explicit if r == repo]
        if explicit and not wanted:
            continue
        sweep(repo, wanted, force, counts[repo])
    lines = [f"{repo}: deleted {c['deleted']}, kept (not integrated) {c['kept']}, refused {c['refused']}" for repo, c in counts.items()]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write("### Branch drafts\n" + "\n".join(f"- {line}" for line in lines) + "\n")


def sweep(repo, wanted, force, count):
    name = repo
    read, write = read_token(repo), delete_token(repo)
    if not read:
        say(f"::warning::{name}: no read token, repository skipped")
        count["refused"] += len(wanted)
        return
    default = None
    status, body = api("GET", f"/repos/{OWNER}/{repo}", read)
    if status == 200:
        default = body["default_branch"]
    elif not force:
        say(f"::warning::{name}: default branch unreadable (HTTP {status}), repository skipped")
        return
    with tempfile.TemporaryDirectory() as directory:
        if not mirror(repo, read, directory):
            say(f"::warning::{name}: clone failed, repository skipped")
            return
        heads = git(directory, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split()
        existing = set(heads)
        candidates = wanted or [h for h in heads if h.startswith("wip-")]
        upstreams = [u for u in dict.fromkeys([UPSTREAM, default]) if u in existing]
        for branch in candidates:
            if not DRAFT.match(branch):
                count["refused"] += 1
                say(f"::warning::{name}: a name outside wip-<id> refused")
                continue
            if branch not in existing:
                say(f"{name}: a requested draft is already gone")
                continue
            if not force and (not upstreams or not integrated(directory, branch, upstreams)):
                count["kept"] += 1
                continue
            if not write:
                count["refused"] += 1
                say(f"::warning::{name}: no token with Contents: write, draft not deleted")
                continue
            code, _ = api("DELETE", f"/repos/{OWNER}/{repo}/git/refs/heads/{branch}", write)
            if code == 204:
                count["deleted"] += 1
            else:
                count["refused"] += 1
                say(f"::warning::{name}: delete refused with HTTP {code} - the token needs Contents: write")
    say(f"{name}: deleted {count['deleted']}, kept {count['kept']}, refused {count['refused']}")


if __name__ == "__main__":
    main()
