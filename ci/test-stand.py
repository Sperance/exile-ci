#!/usr/bin/env python3
"""Тестовый стенд: что на нём стоит (клиент и закреплённый сервер последнего успешного deploy-test) и стоит ли там голова рабочей ветки клиента.

    python3 -I ci/test-stand.py code-changed <клон клиента> <от> <до>
        -> true | false: менялся ли между коммитами код (не .md, не audit/, не .claude/, не номер версии в app/build.gradle.kts); неизвестное «от» - true
    python3 -I ci/test-stand.py record <файл> <коммит клиента или пусто> <закреплённый сервер> <коммит образа> <тег qa-<n> или пусто>
        -> JSON состояния стенда (время выката - сейчас); публикует его ci/test-stand.sh
    python3 -I ci/test-stand.py check <stand.json> <клон клиента> <клон сервера> <голова клиента> <файл вывода>
        -> on_test=true|false и reason= (стоит ли голова на стенде: после коммита стенда менялись только .md, версия и заметки, пин сервера
           тот же или отличается только .md вне образа - ci/server-diff.sh)
    python3 -I ci/test-stand.py report <stand.json|-> <on|off|na> <число открытых Issues test|-> <skip_test true|false> <файл сводки>
        -> markdown для сводки прогона: сколько голова живёт на тесте, открытые Issues `test`, красная строка при skip_test

Коммиты и пути в журнал не выводятся: только счётчики и причина словами. Ошибки - строкой ::error:: и код 1.
"""
import json
import os
import re
import subprocess
import sys
import time

VERSION_FILE = "app/build.gradle.kts"
VERSION_FIELDS = re.compile(r'(versionCode\s*=\s*)\d+|(versionName\s*=\s*)"[^"]*"')
DOC_PREFIXES = ("audit/", ".claude/")
SHA = re.compile(r"^[0-9a-f]{40}$")


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def git(directory, *args):
    return subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, check=False)


def has_commit(directory, sha):
    return bool(SHA.match(sha or "")) and git(directory, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def is_doc(path):
    return path.endswith(".md") or path.startswith(DOC_PREFIXES)


def version_neutral(directory, commit):
    shown = git(directory, "show", f"{commit}:{VERSION_FILE}")
    return VERSION_FIELDS.sub(lambda m: (m.group(1) or m.group(2)) + "_", shown.stdout) if shown.returncode == 0 else None


def code_files(directory, old, new):
    names = git(directory, "diff", "--name-only", old, new).stdout.split()
    code = [name for name in names if not is_doc(name)]
    if VERSION_FILE in code and version_neutral(directory, old) == version_neutral(directory, new):
        code.remove(VERSION_FILE)
    return code


def code_changed(directory, old, new):
    if not (has_commit(directory, old) and has_commit(directory, new)):
        return True
    return bool(code_files(directory, old, new))


def record(target, client, pin, image, tag):
    for label, value in (("pinned server", pin), ("server image", image)):
        if not SHA.match(value):
            fail(f"{label} '{value}' is not a commit")
    if client and not SHA.match(client):
        fail(f"client commit '{client}' is not a commit")
    state = {"client": client, "server": pin, "image": image, "qa": tag, "deployedAt": int(time.time())}
    with open(target, "w", encoding="utf-8") as out:
        json.dump(state, out, sort_keys=True)


def server_same_image(script_dir, server_dir, old, new):
    return old == new or subprocess.run(["bash", os.path.join(script_dir, "server-diff.sh"), server_dir, old, new], check=False).returncode == 0


def verdict(state, client_dir, server_dir, head, script_dir):
    if not has_commit(client_dir, state.get("client", "")):
        return False, "the test stand has no client commit of the working branch history"
    if git(client_dir, "merge-base", "--is-ancestor", state["client"], head).returncode != 0:
        return False, "the test stand client commit is not an ancestor of the head"
    if code_files(client_dir, state["client"], head):
        return False, "the client code changed after the commit that stands on the test stand"
    head_pin = (git(client_dir, "ls-tree", head, "backend").stdout.split() or ["", "", "", ""])[2]
    if not server_same_image(script_dir, server_dir, state["server"], head_pin):
        return False, "the server pinned in the head differs from the one on the test stand"
    return True, "the head is on the test stand"


def check(stand, client_dir, server_dir, head, output):
    state = json.load(open(stand, encoding="utf-8"))
    ok, reason = verdict(state, client_dir, server_dir, head, os.path.dirname(os.path.abspath(__file__)))
    print(f"test stand: {reason}")
    with open(output, "a", encoding="utf-8") as out:
        out.write(f"on_test={'true' if ok else 'false'}\nreason={reason}\n")


def duration(seconds):
    minutes = max(int(seconds // 60), 0)
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    parts = [f"{days} д" if days else "", f"{hours} ч" if hours or days else "", f"{minutes} мин"]
    return " ".join(part for part in parts if part)


def report(stand, state, issues, skip, target):
    lines = ["### Тест перед выпуском"]
    if stand == "-":
        lines.append("- Тестовый стенд: записи о выкате нет.")
    else:
        deployed = json.load(open(stand, encoding="utf-8")).get("deployedAt", 0)
        age = duration(time.time() - deployed)
        lines.append({
            "on": f"- Голова живёт на тесте: {age}.",
            "off": f"- Голова не на тесте; на стенде стоит другой код, выкачен {age} назад.",
            "na": f"- На тестовом стенде стоит выкат {age} давности.",
        }[state])
    lines.append(f"- Открытых Issues с меткой `test`: {issues} (выпуск не блокируют).")
    if skip == "true":
        lines.append("- **выпущено мимо теста**")
        print("::error title=skip_test::выпущено мимо теста")
    with open(target, "a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def main():
    command, args = sys.argv[1], sys.argv[2:]
    if command == "code-changed" and len(args) == 3:
        print("true" if code_changed(*args) else "false")
    elif command == "record" and len(args) == 5:
        record(*args)
    elif command == "check" and len(args) == 5:
        check(*args)
    elif command == "report" and len(args) == 5 and args[1] in ("on", "off", "na"):
        report(*args)
    else:
        fail("usage: test-stand.py code-changed|record|check|report (see the header)")


main()
