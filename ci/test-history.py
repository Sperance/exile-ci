#!/usr/bin/env python3
"""История обновлений теста: запись на тестовую сборку для тестового сервера (client.yml, job qa-release; сервер читает её из тела приватного предрелиза).

    python3 -I ci/test-history.py record <клон клиента> <от коммит или -> <до коммит> <версия x.y.z_test> <номер сборки> <файл пунктов plan> <файл вывода>
        -> JSON записи {"version", "build", "notes": [{"text", "issues", "check"}]}: новые пункты `## Следующая версия` RELEASE_NOTES.md с прошлой тестовой
           сборки (пункт «Техническое» несёт приставку «Техническое: », пункты сервера - метку «[сервер]»; номера Issues - трейлеры `Issue: #N` коммита, что
           добавил пункт) и пункты Test-Plan с check=true
    python3 -I ci/test-history.py marker <файл записи>
        -> строка `<!-- test-update: <base64> -->` для тела приватного предрелиза

Пункты уходят ТОЛЬКО в приватный предрелиз клиентского репозитория и на тестовый сервер: в публичный exile-ci и его журналы они не попадают (журнал - только
счётчики). Только стандартная библиотека. Ошибки - строкой ::error:: и код 1.
"""
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
import notes

NOTES_PATH = "RELEASE_NOTES.md"
SHA = re.compile(r"^[0-9a-f]{40}$")
ISSUE_TRAILER = re.compile(r"^Issue: #(\d+)", re.MULTILINE)
FALLBACK_COMMITS = 30
ITEM_LIMIT = 300
ITEMS_LIMIT = 80
SPLIT = "\x00"


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def git(clone, *args):
    done = net.run(net.READ, ["git", "-C", clone, *args], capture_output=True)
    return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None


def items_at(clone, ref):
    text = git(clone, "show", f"{ref}:{NOTES_PATH}")
    body = notes.next_section(text or "")
    if body is None:
        return []
    parsed = notes.parse(body)
    found = []
    for section, items in parsed.sections.items():
        for item in items:
            if notes.MANDATORY.match(item):
                continue
            text_item = f"Техническое: {item}" if section == notes.STAFF_SECTION and not notes.LEGACY_STAFF.match(item) else item
            found.append(" ".join(text_item.split())[:ITEM_LIMIT])
    return found


def commits(clone, old, new):
    span = [f"{old}..{new}"] if SHA.match(old) else [f"-{FALLBACK_COMMITS}", new]
    out = git(clone, "log", "--reverse", "--format=%H%x00%B%x00%x01", *span, "--", NOTES_PATH)
    if out is None:
        fail("the commits of the test build could not be read")
    found = []
    for block in out.split("\x01"):
        parts = block.strip("\n").split(SPLIT)
        if len(parts) >= 2 and SHA.match(parts[0].strip()):
            found.append((parts[0].strip(), parts[1]))
    return found


def record(clone, old, new, name, code, plan_file, target):
    if not SHA.match(new):
        fail(f"commit '{new}' is not a sha")
    if not code.isdigit():
        fail(f"build number '{code}' is not a number")
    present = items_at(clone, new)
    before = {notes.normalize(item) for item in items_at(clone, old)} if SHA.match(old) else set()
    known = set(before)
    issues_of = {}
    for sha, message in commits(clone, old, new):
        numbers = [int(n) for n in ISSUE_TRAILER.findall(message)]
        for item in items_at(clone, sha):
            key = notes.normalize(item)
            if key not in known:
                known.add(key)
                issues_of[key] = numbers
    fresh = [item for item in present if notes.normalize(item) not in before]
    entries = [{"text": item, "issues": issues_of.get(notes.normalize(item), []), "check": False} for item in fresh[:ITEMS_LIMIT]]
    plan = [line.strip() for line in open(plan_file, encoding="utf-8").read().splitlines() if line.strip()] if plan_file != "-" else []
    entries += [{"text": item, "issues": [], "check": True} for item in plan]
    with open(target, "w", encoding="utf-8") as out:
        json.dump({"version": name, "build": int(code), "notes": entries}, out, ensure_ascii=False)
    print(f"test history: {len(fresh)} note(s), {len(plan)} check item(s)")


def marker(path):
    with open(path, "rb") as source:
        encoded = base64.b64encode(source.read()).decode("ascii")
    print(f"<!-- test-update: {encoded} -->")


def main():
    command, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if command == "record" and len(args) == 7:
        record(*args)
    elif command == "marker" and len(args) == 1:
        marker(*args)
    else:
        fail("usage: test-history.py record <clone> <from|-> <to> <name> <build> <plan file|-> <out> | marker <file>")


main()
