"""Пост в тему «Важное» группы Telegram из IMPORTANT.md сервера: вайп, обязательное обновление, потери игроков.

Файл: первая непустая строка - заголовок (ведущие # срезаются), дальше - текст абзацами, строки «- » - пункты. Текст и решение
публиковать согласует владелец (CLAUDE.md, versions-release.md сервера).
Окружение: TELEGRAM_BOT_TOKEN (секрет), TELEGRAM_CHAT (@группа), TELEGRAM_IMPORTANT_TOPIC (номер темы).
Использование: python3 important.py <файл>; код 1 - пост не вышел.
"""
import html
import os
import sys

from post import LIMIT, Bot, TelegramError, text_length


def compose(source):
    lines = [ln.rstrip() for ln in source.strip().splitlines()]
    title, body = lines[0].lstrip("#").strip(), lines[1:]
    paragraphs = []
    for line in body:
        if line.startswith("- "):
            paragraphs.append(f"▸ {html.escape(line[2:].strip())}")
        elif line.strip():
            paragraphs.append(html.escape(line.strip()))
    text = "\n\n".join([f"❗ <b>{html.escape(title)}</b>"] + paragraphs)
    if text_length(text) > LIMIT:
        raise TelegramError(f"the text is longer than {LIMIT} characters")
    return text


def main(path):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN is not set: no Telegram post")
        return 1
    with open(path, encoding="utf-8") as f:
        source = f.read()
    try:
        Bot(token).call("sendMessage", chat_id=os.environ["TELEGRAM_CHAT"],
                        message_thread_id=int(os.environ["TELEGRAM_IMPORTANT_TOPIC"]), text=compose(source), parse_mode="HTML",
                        link_preview_options={"is_disabled": True})
    except TelegramError as e:
        print(f"::warning::the important post failed: {e}. Repeat: Release → important")
        return 1
    print("telegram: important posted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
