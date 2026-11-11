"""Правка «только документы»: после неё отметка precheck и статус check-wip предка остаются в силе.

Близнец scripts/docs-only.sh сервера (его зовут хук pre-push и scripts/precheck.sh клиента и сервера); списки сверяет сторож guards в Check wip.
Документы: *.md, audit/, .claude/. Не документы: RELEASE_NOTES.md клиента и IMPORTANT.md сервера (их сторожат notes-edit и release guards),
всё из src/main/resources/ сервера. Пин backend/ клиента - документ, если между пинами сервер поменял только документы.

    docs-only.py classify <client|server>               пути со stdin; код 0 - все документы
    docs-only.py parity <docs-only.sh>                  сверка с серверным скриптом на наборе путей; код 1 - разошлись
    docs-only.py trusted <client|server> <репо> <sha> [--server-repo <репо>]
                                                        ворота пуша: sha или его предок, после которого менялись только документы, с check-wip = success
                                                        (ci/check-wip-read.sh); печатает этот коммит, код 1 - такого нет. Окружение: TOKEN (SOURCE_TOKEN).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net  # noqa: E402

DEPTH = 10
API = "https://api.github.com/repos"
SAMPLES = [
    "README.md", "RELEASE_NOTES.md", "IMPORTANT.md", "rules-md/server/ci.md", "RULES.md", "core/STRUCTURE.md",
    "audit/work/handoff.md", "audit/versions.md", ".claude/settings.json", "src/main/resources/admin/notes.md",
    "src/main/resources/content/items.json", "core/src/main/kotlin/A.kt", "backend", "scripts/precheck.sh", "app/build.gradle.kts",
]


def is_doc(kind, path):
    if (kind, path) in (("client", "RELEASE_NOTES.md"), ("server", "IMPORTANT.md")):
        return False
    if kind == "server" and path.startswith("src/main/resources/"):
        return False
    return path.startswith(("audit/", ".claude/")) or path.endswith(".md")


def all_docs(kind, paths):
    return all(is_doc(kind, path) for path in paths if path)


def parity(script):
    differ = []
    for kind in ("client", "server"):
        for path in SAMPLES:
            shell = subprocess.run(["bash", script, "classify", kind], input=path + "\n", text=True, capture_output=True).returncode == 0
            if shell != is_doc(kind, path):
                differ.append(f"{kind} {path}: docs-only.sh {shell}, docs-only.py {is_doc(kind, path)}")
    for line in differ:
        print(f"::error::docs-only lists differ: {line}")
    return not differ


def pin(repo, ref, token):
    found = net.get_json(f"{API}/{repo}/contents/backend?ref={ref}", token)
    return found.get("sha") if found.get("type") == "submodule" else None


def docs_between(kind, repo, old, new, token, server_repo):
    compared = net.get_json(f"{API}/{repo}/compare/{old}...{new}", token)
    if compared.get("status") not in ("ahead", "identical") or compared.get("behind_by", 0):
        return False
    files = compared.get("files") or []
    if len(files) >= 300:
        return False
    for item in files:
        path = item.get("filename", "")
        if kind == "client" and path == "backend":
            old_pin, new_pin = pin(repo, old, token), pin(repo, new, token)
            if not (old_pin and new_pin and server_repo and docs_between("server", server_repo, old_pin, new_pin, token, None)):
                return False
            continue
        if not is_doc(kind, path):
            return False
    return True


def status(repo, sha):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-wip-read.sh")
    lines = subprocess.run(["bash", script, repo, sha], capture_output=True, text=True).stdout.strip().splitlines()
    return lines[-1] if lines else "unreadable"


def trusted(kind, repo, sha, server_repo):
    token = os.environ.get("TOKEN")
    commits = net.get_json(f"{API}/{repo}/commits?sha={sha}&per_page={DEPTH}", token)
    for commit in (item["sha"] for item in commits):
        if commit != sha and not docs_between(kind, repo, commit, sha, token, server_repo):
            return None
        state = status(repo, commit)
        if state == "success":
            return commit
        if state == "unreadable":
            return None
    return None


def main(argv):
    if len(argv) == 2 and argv[0] == "classify":
        return 0 if all_docs(argv[1], sys.stdin.read().splitlines()) else 1
    if len(argv) == 2 and argv[0] == "parity":
        return 0 if parity(argv[1]) else 1
    if len(argv) >= 4 and argv[0] == "trusted":
        server_repo = argv[argv.index("--server-repo") + 1] if "--server-repo" in argv else None
        found = trusted(argv[1], argv[2], argv[3], server_repo)
        if not found:
            return 1
        print(found)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
