"""Пост об обновлении в канал Telegram: заметки релиза (RELEASE_NOTES.md из тела релиза) с баннером крупным превью над текстом
и кнопками RuStore, Google Play и APK. Новый пост закрепляется вместо прошлого.

Повтор без дублей: закреплён пост той же версии - он правится, а не выходит снова. Сбой - предупреждение в журнале и код 0:
релиз уже вышел, пост повторяет ручной запуск (Release → telegram).
Окружение: TELEGRAM_BOT_TOKEN (секрет), TELEGRAM_CHAT (@канал), GITHUB_SERVER_URL и GITHUB_REPOSITORY (их ставит Actions).
Использование: python3 post.py <тег> <файл заметок> <URL баннера>
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

LIMIT = 4096
MANDATORY = re.compile(r"^обновление обязательное\.?$", re.I)
LEAD = re.compile(r"^(?P<lead>[^:.!?]{2,40}):\s+(?P<rest>.+)$")
PACKAGE = "com.sperance.exileforge"


class TelegramError(Exception):
    pass


def text_length(text):
    """Длина, как её считает Telegram: видимый текст без разметки, в единицах UTF-16."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)).encode("utf-16-le")) // 2


def bullet(item):
    """Пункт: короткая шапка до двоеточия - жирным; «Техническое» - курсивом целиком, это строка не для всех."""
    m = LEAD.match(item)
    if not m:
        return f"▸ {html.escape(item)}"
    if m["lead"].lower().startswith("техническ"):
        return f"<i>{html.escape(item)}</i>"
    return f"▸ <b>{html.escape(m['lead'])}</b>: {html.escape(m['rest'])}"


def compose(header, notes, release_url):
    """Текст поста. Обязательность - сразу под заголовком; не влезает в лимит - пункты с конца уходят, внизу ссылка на релиз."""
    items = [ln.strip()[2:].strip() for ln in notes.splitlines() if ln.strip().startswith("- ")]
    mandatory = any(MANDATORY.match(i) for i in items)
    body = [bullet(i) for i in items if not MANDATORY.match(i)]
    head = [f"<b>{html.escape(header)}</b>"] + (["❗ <b>Обновление обязательное</b>"] if mandatory else [])
    more = f'<a href="{release_url}">Все изменения</a>'
    text = "\n\n".join(head + body)
    while text_length(text) > LIMIT and body:
        body.pop()
        text = "\n\n".join(head + body + [more])
    return text


def keyboard(apk_url):
    return {"inline_keyboard": [
        [{"text": "RuStore", "url": f"https://www.rustore.ru/catalog/app/{PACKAGE}"},
         {"text": "Google Play", "url": f"https://play.google.com/store/apps/details?id={PACKAGE}"}],
        [{"text": "Скачать APK", "url": apk_url}],
    ]}


class Bot:
    def __init__(self, token):
        self._token = token

    def call(self, method, **params):
        """Вызов Bot API; 429 и сбои сети или сервера Telegram - до трёх попыток, остальные ошибки - сразу."""
        data = json.dumps(params).encode()
        for attempt in range(3):
            request = urllib.request.Request(f"https://api.telegram.org/bot{self._token}/{method}", data,
                                             {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)["result"]
            except urllib.error.HTTPError as e:
                reply = json.loads(e.read() or b"{}")
                description = reply.get("description", f"HTTP {e.code}")
                retry_after = reply.get("parameters", {}).get("retry_after")
                if attempt == 2 or not (retry_after or e.code >= 500):
                    raise TelegramError(f"{method}: {description}") from None
                time.sleep(retry_after or 5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 2:
                    raise TelegramError(f"{method}: {getattr(e, 'reason', e)}") from None
                time.sleep(5 * (attempt + 1))


def wait_for_image(url, timeout=180):
    """Pages выкладывает файл не мгновенно: превью, снятое до появления картинки, Telegram запомнит пустым."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                if response.headers.get_content_type().startswith("image/"):
                    return
        except urllib.error.URLError:
            pass
        if time.monotonic() > deadline:
            raise TelegramError("the banner did not appear on GitHub Pages")
        time.sleep(10)


def publish(bot, chat, header, text, banner_url, markup):
    content = {
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"url": banner_url, "prefer_large_media": True, "show_above_text": True},
        "reply_markup": markup,
    }
    pinned = bot.call("getChat", chat_id=chat).get("pinned_message") or {}
    if pinned.get("text", "").split("\n", 1)[0] == header:
        try:
            bot.call("editMessageText", chat_id=chat, message_id=pinned["message_id"], **content)
        except TelegramError as e:
            if "message is not modified" not in str(e):
                raise
        return "edited"
    message = bot.call("sendMessage", chat_id=chat, **content)
    # Пост уже прозвенел - закреп без второго уведомления
    bot.call("pinChatMessage", chat_id=chat, message_id=message["message_id"], disable_notification=True)
    return "posted"


def main(tag, notes_file, banner_url):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN is not set: no Telegram post")
        return
    releases = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/releases"
    header = f"Обновление {tag.removeprefix('v')}"
    with open(notes_file, encoding="utf-8") as f:
        text = compose(header, f.read(), f"{releases}/tag/{tag}")
    markup = keyboard(f"{releases}/download/{tag}/ExileForge-{tag}.apk")
    try:
        wait_for_image(banner_url)
        result = publish(Bot(token), os.environ["TELEGRAM_CHAT"], header, text, banner_url, markup)
    except TelegramError as e:
        print(f"::warning::Telegram post of {tag} failed: {e}. Repeat: Release → telegram")
        return
    print(f"telegram: {result} {tag}, {text_length(text)} of {LIMIT} characters")


if __name__ == "__main__":
    main(*sys.argv[1:4])
