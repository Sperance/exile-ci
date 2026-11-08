"""Пост об обновлении сервера в тему «Обновления» (Release → server без клиента): новые пункты заметок с меткой «[сервер]».

Берутся пункты раздела `## Следующая версия` RELEASE_NOTES.md рабочей ветки клиента с меткой «[сервер]» (ci/notes.py), которых ещё не
было в постах: пункт вышел, если в этом репозитории есть тег server-note-<12 знаков sha256 пункта> (файл со списком имён тегов -
второй аргумент). Кнопок магазинов нет. Выпуск клиента переименовывает раздел, и его пункты уходят блоком «Уже в игре» поста версии.
Не влезло в лимит - лишние пункты остаются на следующий раз. Имена тегов вышедших пунктов пишутся в третий аргумент; тег ставит
workflow. Окружение: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT, TELEGRAM_TOPIC.
Использование: python3 server_notes.py <RELEASE_NOTES.md> <файл имён тегов> <файл новых тегов>; код 1 - пост не вышел.
"""
import hashlib
import html
import os
import sys

from post import LIMIT, Bot, TelegramError, bullet, russian_date, text_length, release_notes


def tag_of(item):
    return "server-note-" + hashlib.sha256(release_notes.normalize(item).encode("utf-8")).hexdigest()[:12]


def fresh(source, posted):
    """Новые пункты сервера в порядке файла: (пункт без метки, тег)."""
    body = release_notes.next_section(source)
    if body is None:
        return []
    found = {}
    for item in release_notes.parse(body).all_items():
        if release_notes.is_server(item) and tag_of(item) not in posted:
            found.setdefault(tag_of(item), release_notes.strip_server(item))
    return [(item, tag) for tag, item in found.items()]


def compose(items):
    """Текст и теги вошедших пунктов; пункты, что не влезли, остаются без тега."""
    head = f"<b>Обновление сервера · {html.escape(russian_date())}</b>"
    lines, tags = [], []
    for item, tag in items:
        candidate = "\n\n".join([head] + lines + [bullet(item)])
        if text_length(candidate) > LIMIT:
            break
        lines.append(bullet(item))
        tags.append(tag)
    return "\n\n".join([head] + lines), tags


def main(source_path, posted_path, out_path):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN is not set: no Telegram post")
        return 1
    with open(posted_path, encoding="utf-8") as f:
        posted = {line.strip().rsplit("/", 1)[-1] for line in f if line.strip()}
    with open(source_path, encoding="utf-8") as f:
        items = fresh(f.read(), posted)
    if not items:
        print("telegram: no new server notes")
        return 0
    text, tags = compose(items)
    if not tags:
        print("::warning::a server note is longer than the Telegram limit")
        return 1
    try:
        Bot(token).call("sendMessage", chat_id=os.environ["TELEGRAM_CHAT"], message_thread_id=int(os.environ["TELEGRAM_TOPIC"]),
                        text=text, parse_mode="HTML", link_preview_options={"is_disabled": True})
    except TelegramError as e:
        print(f"::warning::the server notes post failed: {e}. Repeat: Release → server-notes")
        return 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(tags) + "\n")
    print(f"telegram: {len(tags)} server notes posted")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
