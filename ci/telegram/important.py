"""Пост в тему «Важное» группы Telegram из IMPORTANT.md сервера: вайп, обязательное обновление, потери игроков.

Файл накопительный: заголовка в нём нет, работы добавляют темы `### <тема>` (дальше абзацы, строки «- » - пункты). Заголовок поста ставит
CI: «Важное в обновлении <версия> · <дата>» при выпуске клиента, «Важное · <дата>» при Release → server без клиента. Прежний вид -
первая строка `# заголовок` - читается как первая тема. Текст и решение публиковать согласует владелец (CLAUDE.md, telegram.md сервера).
Окружение: TELEGRAM_BOT_TOKEN (секрет), TELEGRAM_CHAT (@группа), TELEGRAM_IMPORTANT_TOPIC (номер темы).
Использование: python3 important.py <файл> [версия выпуска клиента]; код 1 - пост не вышел.
"""
import html
import os
import sys

from post import LIMIT, Bot, TelegramError, russian_date, text_length


def heading(version=""):
    return f"Важное в обновлении {version} · {russian_date()}" if version else f"Важное · {russian_date()}"


def compose(source, version=""):
    paragraphs = []
    for raw in source.strip().splitlines():
        line = raw.strip()
        if line.startswith("#"):
            paragraphs.append(f"<b>{html.escape(line.lstrip('#').strip())}</b>")
        elif line.startswith("- "):
            paragraphs.append(f"▸ {html.escape(line[2:].strip())}")
        elif line:
            paragraphs.append(html.escape(line))
    text = "\n\n".join([f"❗ <b>{html.escape(heading(version))}</b>"] + paragraphs)
    if text_length(text) > LIMIT:
        raise TelegramError(f"the text is longer than {LIMIT} characters")
    return text


def main(path, version=""):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN is not set: no Telegram post")
        return 1
    with open(path, encoding="utf-8") as f:
        source = f.read()
    try:
        Bot(token).call("sendMessage", chat_id=os.environ["TELEGRAM_CHAT"],
                        message_thread_id=int(os.environ["TELEGRAM_IMPORTANT_TOPIC"]), text=compose(source, version), parse_mode="HTML",
                        link_preview_options={"is_disabled": True})
    except TelegramError as e:
        print(f"::warning::the important post failed: {e}. Repeat: Release → important")
        return 1
    print("telegram: important posted")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
