#!/usr/bin/env python3
"""Сторож общей сети теста и боя: Caddy боя ходит к игре боя только по псевдониму, к тесту - по имени теста.

    python3 -I ci/guard-edge.py [--snippet <deploy/test/Caddyfile.snippet>] [--install <deploy/test/install.sh>]

Тест и бой на одном VPS делят Caddy боя через сеть edge; сервис игры в обоих проектах называется `game`, и Docker регистрирует это имя
во всех сетях контейнера: `reverse_proxy game:` в Caddyfile боя ведёт и на тест (бой отдавал тестовый стенд). Красное:
  - в блоке теста (Caddyfile.snippet) прокси не на exileforge-test-game или голое имя game;
  - install.sh не даёт игре боя псевдоним exileforge-prod-game или не переписывает голое имя в Caddyfile боя (BARE_PROXY).
Файлы сервера передаёт job guards в check-wip.yml (git show из клона сервера); без файлов (ci/precheck.sh) - пропуск с пометкой.
"""
import argparse
import re
import sys

PROD_ALIAS = "exileforge-prod-game"
TEST_NAME = "exileforge-test-game"


def snippet_errors(text):
    errors = []
    targets = re.findall(r"^\s*reverse_proxy\s+([^\s:]+):", text, re.MULTILINE)
    if not targets:
        errors.append("Caddyfile.snippet has no reverse_proxy")
    for target in targets:
        if target != TEST_NAME:
            errors.append(f"Caddyfile.snippet proxies to {target}, the test block must use {TEST_NAME}")
    return errors


def install_errors(text):
    errors = []
    if f"PROD_ALIAS={PROD_ALIAS}" not in text:
        errors.append(f"install.sh does not define PROD_ALIAS={PROD_ALIAS}")
    if "aliases:" not in text or "$PROD_ALIAS" not in text:
        errors.append("install.sh does not give the prod game the alias in compose.edge.yaml")
    if not re.search(r'sed -E "s/\$BARE_PROXY/reverse_proxy \$PROD_ALIAS:/"', text):
        errors.append("install.sh does not rewrite the bare game name in the prod Caddyfile")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippet")
    parser.add_argument("--install")
    args = parser.parse_args()
    if not args.snippet and not args.install:
        print("edge guard: green (server files not given)")
        return 0
    errors = []
    if args.snippet:
        with open(args.snippet, encoding="utf-8") as handle:
            errors += snippet_errors(handle.read())
    if args.install:
        with open(args.install, encoding="utf-8") as handle:
            errors += install_errors(handle.read())
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("edge guard: green")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
