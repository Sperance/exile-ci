#!/usr/bin/env python3
"""Сторож сети CI: голый сетевой вызов вне ci/net.py и ci/retry.sh - красный (job guards в check-wip.yml, шаг в job'ах changes client.yml и resolve server.yml).

    python3 -I ci/guard-network.py [корень репозитория]

Ищет в .github/workflows/*.yml, .github/actions/*/action.yml (блоки run), ci/**/*.sh и ci/**/*.py:
  bash: gh (api, release, issue, label, workflow, run, pr, repo), curl, wget, git clone|fetch|ls-remote|pull|push без `bash ci/retry.sh <режим>` или `netcall <режим>` перед ним;
  python: импорт urllib.request, http.client, requests, urllib3, httpx, вызовы .get|.post|.put|.patch|.delete|.request на объекте http или session,
          subprocess и os.system с curl, wget, gh, git clone|fetch|ls-remote|pull|push (нужен net.run).
Допущенное - строка в ci/net-allowlist.txt: `путь | подстрока строки или * | причина`; запись без причины или без совпадения (устарела) - тоже красная.
Режимы read, idem, once и правила повторов - в шапке ci/retry.sh и ci/net.py.
"""
import ast
import glob
import os
import re
import sys

import yaml

COMMAND = re.compile(r"(?<![\w./$-])(gh (?:api|release|issue|label|workflow|run|pr|repo)\b|curl\b|wget\b|git (?:-C \S+ )?(?:clone|ls-remote|fetch|pull|push)\b)")
CONTEXT_OK = re.compile(r"(^\s*|\$\(|\|\| |&& |; |\| |\{ |! |\bthen |\bif |\bdo |`|\w+=\S* |\w+=\"[^\"]*\" |\bsh -c '|\brun: |quiet\.sh [\w-]+ |\)\s+)$")
SKIP_LINE = re.compile(r"^\s*(#|echo\b|printf\b)")
WRAPPED = re.compile(r"(retry\.sh|netcall) (read|idem|once) $")
NETWORK_MODULES = {"urllib.request", "http.client", "requests", "urllib3", "httpx", "aiohttp", "ftplib", "smtplib"}
NETWORK_ROOTS = {"requests", "urllib3", "httpx", "aiohttp"}
NETWORK_VERBS = {"get", "post", "put", "patch", "delete", "request"}
NETWORK_CLIENT_NAMES = {"http", "session"}
GIT_NETWORK = {"clone", "fetch", "ls-remote", "pull", "push"}
SUBPROCESS_CALLS = {"run", "call", "check_call", "check_output", "Popen"}


def shell_violations(text):
    for line in text.splitlines():
        if SKIP_LINE.match(line):
            continue
        for match in COMMAND.finditer(line):
            before = line[:match.start()]
            if WRAPPED.search(before) or not CONTEXT_OK.search(before):
                continue
            if "$(" not in before[-2:] and before.count('"') % 2 == 1:
                continue
            yield line.strip()


def yaml_snippets(path):
    document = yaml.safe_load(open(path, encoding="utf-8"))
    jobs = (document.get("jobs") or {}).items() if "jobs" in document else [("action", document.get("runs") or {})]
    for job, body in jobs:
        for step in body.get("steps") or []:
            if isinstance(step.get("run"), str):
                yield f"{job}/{step.get('name') or 'run'}", step["run"]


def argv_of(node):
    if not node.args:
        return []
    first = node.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        return [e.value for e in first.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split()
    return []


def is_network_argv(argv):
    if not argv:
        return False
    if argv[0] in ("curl", "wget", "gh"):
        return True
    return argv[0] == "git" and any(word in GIT_NETWORK for word in argv[1:6])


def python_violations(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in NETWORK_MODULES or alias.name.split(".")[0] in NETWORK_ROOTS:
                    yield f"import {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module and (node.module in NETWORK_MODULES or node.module.split(".")[0] in NETWORK_ROOTS):
            yield f"from {node.module} import ..."
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            owner = func.value
            owner_name = owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else ""
            if func.attr in NETWORK_VERBS and owner_name in NETWORK_CLIENT_NAMES:
                yield f"{owner_name}.{func.attr}(...)"
            elif owner_name == "subprocess" and func.attr in SUBPROCESS_CALLS and is_network_argv(argv_of(node)):
                yield "subprocess." + func.attr + " " + " ".join(argv_of(node)[:3])
            elif owner_name == "os" and func.attr in ("system", "popen") and any(w in " ".join(argv_of(node)) for w in ("curl ", "gh ", "git fetch", "git clone")):
                yield f"os.{func.attr} network command"


def collect(root):
    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml")) + glob.glob(os.path.join(root, ".github", "actions", "*", "action.yml"))):
        relative = os.path.relpath(path, root)
        for where, text in yaml_snippets(path):
            for line in shell_violations(text):
                yield relative, where, line
    for path in sorted(glob.glob(os.path.join(root, "ci", "**", "*"), recursive=True)):
        relative = os.path.relpath(path, root)
        if path.endswith(".sh"):
            for line in shell_violations(open(path, encoding="utf-8").read()):
                yield relative, "script", line
        elif path.endswith(".py"):
            for line in python_violations(path):
                yield relative, "script", line


def load_allowlist(root):
    entries, problems = [], []
    path = os.path.join(root, "ci", "net-allowlist.txt")
    for number, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.split("|", 2)]
        if len(parts) != 3 or not all(parts) or len(parts[2]) < 10:
            problems.append(f"ci/net-allowlist.txt:{number}: expected `path | needle or * | reason (at least 10 characters)`")
            continue
        entries.append((parts[0], parts[1], parts[2]))
    return entries, problems


def main():
    root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entries, problems = load_allowlist(root)
    used = set()
    for path, where, text in collect(root):
        allowed = next((i for i, (p, needle, _) in enumerate(entries) if p == path and (needle == "*" or needle in text)), None)
        if allowed is None:
            problems.append(f"{path} ({where}): raw network call outside ci/net.py and ci/retry.sh: {text[:140]}")
        else:
            used.add(allowed)
    problems += [f"ci/net-allowlist.txt: the entry `{p} | {n}` matches nothing: remove it" for i, (p, n, _) in enumerate(entries) if i not in used]
    for problem in problems:
        print(f"::error::{problem}")
    print(f"network guard: {'RED, ' + str(len(problems)) + ' problem(s)' if problems else 'green'} ({len(entries)} allowlist entries)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
