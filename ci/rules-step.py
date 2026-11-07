#!/usr/bin/env python3
"""Одна версия правил за выпуск (job `checks` server.yml): RULES_VERSION сервера не выше правил последнего релиза клиента + 1.

    python3 ci/rules-step.py <каталог с исходниками сервера>

Сборка играет только со своими и прежними правилами (`rules-md/common/process/revision-window.md` сервера), поэтому выпуск может
поднять правила лишь на одну версию: иначе новый клиент и прежние сборки не уживутся ни на одном сервере. Выпуски накопительные -
вторая работа до выпуска ставит свои ворота `era.since(...)` на уже поднятую версию, а не поднимает её снова. Правила последнего
релиза - поле rules его update.json в exile-ci; релиза нет - проверять не с чем. В журнал - только числа.
"""
import os
import sys

from store_common import Catalog, say

CONTENT = "rules/src/main/kotlin/com/sperance/exileforge/rules/content/Content.kt"


def rules_version(source):
    with open(os.path.join(source, CONTENT), encoding="utf-8") as file:
        for line in file:
            if line.startswith("const val RULES_VERSION = "):
                return int(line.split("=", 1)[1].strip())
    say("::error::RULES_VERSION not found in the server source")
    sys.exit(1)


def main():
    rules = rules_version(sys.argv[1])
    latest = Catalog().latest()
    if latest is None or "rules" not in latest:
        say("::warning::no released client with rules to compare RULES_VERSION against")
        return
    released = int(latest["rules"])
    if rules > released + 1:
        say(f"::error::RULES_VERSION {rules} is more than one above the rules {released} of the last release {latest.get('versionName')}: "
            f"one rules version per release - gate the change at {released + 1} instead of raising it again")
        sys.exit(1)
    say(f"rules {rules}: within one version of the last release ({released})")


if __name__ == "__main__":
    main()
