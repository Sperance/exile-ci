# CLAUDE.md

- Новые ветки (локальные и удалённые) создавать запрещено, пока владелец явно не попросит. Запрет закреплён хуком `.claude/hooks/no-new-branches.py` и правилами в `.claude/settings.json` - не обходить и не править их.
- Рабочая ветка - `main`: workflow запускаются только с неё. Промежуточные коммиты - в черновик `wip` (`git push origin HEAD:refs/heads/wip`, workflow на нём не запускаются); в `main` правки попадают одним fast-forward пушем из `wip` в конце работы, раньше пушей сервера (ktor-bestgame) и клиента (ExileForge), чтобы их CI шёл уже по новым workflow. Порядок и правила черновиков - `rules-md/common/process/versions-release.md` сервера.
- Локально черновик - ветка `wip`, отслеживающая `origin/wip` (`git fetch origin wip && git checkout wip`); коммиты - только в ней: локальный `main` не опережает origin, иначе стоп-хук облачной сессии требует пуш в `main`. Финальный пуш - `git push origin wip:main` (fast-forward).
- Репозиторий публичный: журналы и артефакты видны всем, код, данные и секреты в них не выводить (`ci/quiet.sh`, шифрование `LOG_KEY`).
- Gradle в сессиях агента - только из кэша: архив prerelease `gradle-cache` клиента (job `gradle-cache` в `client.yml` здесь его собирает, хук клиента `.claude/hooks/gradle-cache.sh` распаковывает в общий `GRADLE_USER_HOME`); заново зависимости не качать.
