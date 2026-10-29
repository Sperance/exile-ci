#!/usr/bin/env python3
"""Хук PreToolUse: запрещает создавать новые ветки (локальные и удалённые), пока владелец явно не попросит.

Блокирует: git checkout -b/-B, git switch -c/-C, git branch <имя>, git push в ветку, которой нет в origin,
и инструмент GitHub MCP create_branch. Выход с кодом 2 - отказ, текст из stderr читает Claude.
"""
import json
import re
import subprocess
import sys

DENY = (
    "Создание новых веток запрещено владельцем (CLAUDE.md). "
    "Работай только в уже существующей ветке; ветку создаёт только владелец по явной просьбе."
)


def deny(reason: str) -> None:
    print(f"{DENY} ({reason})", file=sys.stderr)
    sys.exit(2)


def remote_has_branch(name: str) -> bool:
    out = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", name],
        capture_output=True,
        timeout=30,
    )
    return out.returncode == 0


def current_branch() -> str:
    out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip()


def push_targets(args: list[str]) -> list[str]:
    positional = [a for a in args if not a.startswith("-")]
    refspecs = positional[1:]  # первый - remote
    if not refspecs:
        return [current_branch()]
    targets = []
    for spec in refspecs:
        dst = spec.lstrip("+").split(":")[-1]
        targets.append(re.sub(r"^refs/heads/", "", dst))
    return targets


def check_bash(command: str) -> None:
    for part in re.split(r"&&|\|\||;|\||\n", command):
        tokens = part.split()
        while tokens and re.match(r"^\w+=", tokens[0]):
            tokens = tokens[1:]
        if len(tokens) < 2 or tokens[0] != "git":
            continue
        # пропускаем глобальные опции вида -C dir / -c k=v
        i = 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 2 if tokens[i] in ("-C", "-c") else 1
        if i >= len(tokens):
            continue
        sub, rest = tokens[i], tokens[i + 1:]
        if sub == "checkout" and any(a in ("-b", "-B", "--orphan") for a in rest):
            deny("git checkout -b")
        if sub == "switch" and any(a in ("-c", "-C", "--create", "--force-create", "--orphan") for a in rest):
            deny("git switch -c")
        if sub == "branch":
            flags = [a for a in rest if a.startswith("-")]
            names = [a for a in rest if not a.startswith("-")]
            if any(f in ("-c", "-C", "-m", "-M", "--copy", "--move") for f in flags):
                deny("git branch copy/move")
            read_only = {"-a", "-r", "-l", "-v", "-vv", "--list", "--show-current", "--contains", "--merged",
                         "--no-merged", "-d", "-D", "--delete", "--all", "--remotes", "-u", "--set-upstream-to",
                         "--unset-upstream"}
            if names and not any(f in read_only for f in flags):
                deny("git branch <имя>")
        if sub == "push":
            if any(a in ("--delete", "-d") for a in rest):
                continue
            for target in push_targets(rest):
                if target and target not in ("HEAD",) and not remote_has_branch(target):
                    deny(f"push в несуществующую ветку {target}")


def main() -> None:
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    if tool.endswith("create_branch"):
        deny("create_branch")
    if tool == "Bash":
        check_bash(event.get("tool_input", {}).get("command", ""))


main()
