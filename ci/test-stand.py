#!/usr/bin/env python3
"""Тестовый стенд: что на нём стоит (клиент и закреплённый сервер последнего успешного deploy-test) и стоит ли там голова рабочей ветки клиента.

    python3 -I ci/test-stand.py code-changed <клон клиента> <от> <до>
        -> true | false: менялся ли между коммитами код (не .md, не audit/, не .claude/, не номер версии в app/build.gradle.kts); неизвестное «от» - true
    python3 -I ci/test-stand.py record <файл> <коммит клиента или пусто> <закреплённый сервер> <коммит образа> <тег qa-<n> или пусто> [<коммит последнего выката боя> <k> <версия x.y.z_test>]
        -> JSON состояния стенда (время выката - сейчас; база боя, k и версия теста - если заданы); публикует его ci/test-stand.sh
    python3 -I ci/test-stand.py version <версия образа последнего выката боя x.y.z> <коммит этого выката> <прошлый stand.json|-> <коммит образа теста> <файл вывода>
        -> name=<x.y.z+k>_test, k=, base=: версия сервера теста - последняя выкаченная боевая версия + k patch, k - порядковый номер тестового обновления
           сервера после выката боя (другой образ при той же базе - k прошлой записи + 1, тот же образ - то же число, новая база - 1)
    python3 -I ci/test-stand.py image-version
        -> версия сервера из меток образа (ответ docker buildx imagetools inspect --format '{{json .}}' - в stdin); код 1 - метки с версией нет
    python3 -I ci/test-stand.py check <stand.json> <клон клиента> <клон сервера> <голова клиента> <файл вывода>
        -> on_test=true|false и reason= (стоит ли голова на стенде: после коммита стенда менялись только .md, версия и заметки, пин сервера
           тот же или отличается только .md вне образа - ci/server-diff.sh)
    python3 -I ci/test-stand.py report <stand.json|-> <on|off|na|disabled> <число открытых Issues test|-> <skip_test true|false> <файл сводки>
        -> markdown для сводки прогона: сколько голова живёт на тесте, открытые Issues `test`, красная строка при skip_test

    python3 -I ci/test-stand.py live-extract <файл вывода>      (ответ static/index.json теста - в stdin)
        -> только блок `stand` с известными полями (коммит образа, версия сервера, выпуск баланса, отличие от боя, время выката); код 4 - блока нет
    python3 -I ci/test-stand.py live-check <stand.json|-> <live.json|-> <файл вывода>
        -> alive=true|false, image_ok=true|false и reason=: стенд отвечает и стоит на образе записи о выкате
    python3 -I ci/test-stand.py state-block <stand.json|-> <live.json|-> <файл сводки>
        -> блок «Состояние теста»: жив, образ, возраст выката, отличие баланса от боя

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
PROD_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TEST_SERVER = re.compile(r"^\d+\.\d+\.\d+_test$")
VERSION_LABEL = "org.opencontainers.image.version"


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


def record(target, client, pin, image, tag, base="", k="", version=""):
    for label, value in (("pinned server", pin), ("server image", image)):
        if not SHA.match(value):
            fail(f"{label} '{value}' is not a commit")
    if client and not SHA.match(client):
        fail(f"client commit '{client}' is not a commit")
    state = {"client": client, "server": pin, "image": image, "qa": tag, "deployedAt": int(time.time())}
    if base:
        if not (SHA.match(base) and k.isdigit() and TEST_SERVER.match(version)):
            fail("the prod base, k or the test server version of the record is malformed")
        state.update({"base": base, "k": int(k), "version": version})
    with open(target, "w", encoding="utf-8") as out:
        json.dump(state, out, sort_keys=True)


def test_server_version(prod, base, previous, image, target):
    found = PROD_VERSION.match(prod)
    if not found or not SHA.match(base) or not SHA.match(image):
        fail("the prod server version, its commit or the test image commit is malformed")
    major, minor, patch = (int(part) for part in found.groups())
    state = read_json(previous) or {}
    k = 1
    if state.get("base") == base and isinstance(state.get("k"), int) and state["k"] >= 1:
        k = state["k"] if state.get("image") == image else state["k"] + 1
    name = f"{major}.{minor}.{patch + k}_test"
    print(f"test server version: k={k}")
    with open(target, "a", encoding="utf-8") as out:
        out.write(f"name={name}\nk={k}\nbase={base}\n")


def labels_of(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() == "labels" and isinstance(value, dict) and VERSION_LABEL in value:
                return value
            found = labels_of(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = labels_of(value)
            if found:
                return found
    return None


def image_version():
    try:
        labels = labels_of(json.load(sys.stdin))
    except ValueError:
        labels = None
    version = str((labels or {}).get(VERSION_LABEL, ""))
    if not PROD_VERSION.match(version):
        fail("the image carries no server version label")
    print(version)


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


LIVE_FIELDS = {"commit": str, "deployedAt": int, "serverVersion": str, "balanceRelease": int, "differsFromProd": bool}


def live_extract(target):
    try:
        stand = json.load(sys.stdin).get("stand")
    except (ValueError, AttributeError):
        stand = None
    if not isinstance(stand, dict) or not SHA.match(str(stand.get("commit", ""))):
        print("::warning::the test stand does not answer with a stand block")
        sys.exit(4)
    kept = {key: stand[key] for key, kind in LIVE_FIELDS.items() if isinstance(stand.get(key), kind) and not (kind is int and isinstance(stand.get(key), bool))}
    with open(target, "w", encoding="utf-8") as out:
        json.dump(kept, out, sort_keys=True)


def read_json(path):
    return None if path == "-" or not os.path.exists(path) else json.load(open(path, encoding="utf-8"))


def live_verdict(stand, live):
    if live is None:
        return False, False, "the test stand does not answer"
    if stand is None or stand.get("image") != live.get("commit"):
        return True, False, "the test stand runs another image than the last recorded deploy"
    return True, True, "the test stand is alive and runs the recorded image"


def live_check(stand, live, output):
    alive, image_ok, reason = live_verdict(read_json(stand), read_json(live))
    print(f"test stand: {reason}")
    with open(output, "a", encoding="utf-8") as out:
        out.write(f"alive={str(alive).lower()}\nimage_ok={str(image_ok).lower()}\nreason={reason}\n")


def state_block(stand, live, target):
    recorded, answer = read_json(stand), read_json(live)
    lines = ["### Состояние теста"]
    if answer is None:
        lines.append("- Стенд **не отвечает**.")
    else:
        lines.append("- Стенд жив.")
        lines.append(f"- Образ: `{str(answer.get('commit', ''))[:7] or '?'}`, версия сервера {answer.get('serverVersion') or '?'}" + (" (как в записи о выкате)." if recorded and recorded.get("image") == answer.get("commit") else " (не тот, что в записи о выкате)."))
        if answer.get("deployedAt"):
            lines.append(f"- Выкат на стенде: {duration(time.time() - answer['deployedAt'] / 1000)} назад.")
        release = answer.get("balanceRelease")
        lines.append(f"- Баланс теста: {'выпуск №' + str(release) if release is not None else 'свой выпуск не публиковался'}.")
        differs = answer.get("differsFromProd")
        lines.append("- Баланс отличается от боя: " + ("не известно (базы боя на тесте нет)." if differs is None else ("**да**." if differs else "нет.")))
    with open(target, "a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def duration(seconds):
    minutes = max(int(seconds // 60), 0)
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    parts = [f"{days} д" if days else "", f"{hours} ч" if hours or days else "", f"{minutes} мин"]
    return " ".join(part for part in parts if part)


def report(stand, state, issues, skip, target):
    lines = ["### Тест перед выпуском"]
    if state == "disabled":
        lines.append("- **тестовый стенд не включён**: выпуск идёт без проверки на тесте (нет переменной TEST_SERVER_URL).")
        print("::error title=test stand::тестовый стенд не включён")
    elif stand == "-":
        lines.append("- Тестовый стенд: записи о выкате нет.")
    else:
        deployed = json.load(open(stand, encoding="utf-8")).get("deployedAt", 0)
        age = duration(time.time() - deployed)
        lines.append({
            "on": f"- Голова живёт на тесте: {age}.",
            "off": f"- Голова не на тесте; на стенде стоит другой код, выкачен {age} назад.",
            "na": f"- На тестовом стенде стоит выкат {age} давности.",
        }[state])
    if state != "disabled":
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
    elif command == "record" and len(args) in (5, 8):
        record(*args)
    elif command == "version" and len(args) == 5:
        test_server_version(*args)
    elif command == "image-version" and not args:
        image_version()
    elif command == "check" and len(args) == 5:
        check(*args)
    elif command == "report" and len(args) == 5 and args[1] in ("on", "off", "na", "disabled"):
        report(*args)
    elif command == "live-extract" and len(args) == 1:
        live_extract(*args)
    elif command == "live-check" and len(args) == 3:
        live_check(*args)
    elif command == "state-block" and len(args) == 3:
        state_block(*args)
    else:
        fail("usage: test-stand.py code-changed|record|version|image-version|check|report|live-extract|live-check|state-block (see the header)")


main()
