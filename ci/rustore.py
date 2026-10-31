#!/usr/bin/env python3
"""RuStore public API: загрузка APK, черновик версии, отправка на модерацию с автопубликацией и чтение статусов версий.

Секреты: RUSTORE_KEY_ID и RUSTORE_PRIVATE_KEY (закрытый ключ из консоли RuStore: PEM или base64 DER; значения нигде не печатаются).
Нужны пакеты requests и cryptography (.github/actions/store-tools). Пакет приложения - APP_ID из ci/build-tasks.env. Весь вывод
скрипта перехватывает ci/quiet.sh.

Запуск (из каталога с распакованным APK):
    python3 ci/rustore.py upload <app.apk> <update.json>
"""
import base64
import datetime
import os
import sys

import requests

from store_common import fail, load_update, say, short_notes

BASE = "https://public-api.rustore.ru"
NOTES_LIMIT = 4000
# Версия в магазине у игроков: ACTIVE - опубликована; остальные статусы (DRAFT, MODERATION, APPROVED до публикации, REJECTED) - ещё нет
LIVE = {"ACTIVE", "PUBLISHED"}


class RuStoreError(RuntimeError):
    pass


def load_key(text):
    from cryptography.hazmat.primitives import serialization

    text = text.strip()
    if "BEGIN" in text:
        return serialization.load_pem_private_key(text.encode(), None)
    raw = base64.b64decode(text)
    try:
        return serialization.load_der_private_key(raw, None)
    except ValueError:
        # base64 от PEM-файла
        return serialization.load_pem_private_key(raw, None)


class RuStore:
    def __init__(self, key_id, private_key, package):
        self.package = package
        self.http = requests.Session()
        self.http.headers["Public-Token"] = self._token(key_id, load_key(private_key))

    def _token(self, key_id, key):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        signature = base64.b64encode(key.sign((key_id + stamp).encode(), padding.PKCS1v15(), hashes.SHA512())).decode()
        response = requests.post(f"{BASE}/public/auth/", json={"keyId": key_id, "timestamp": stamp, "signature": signature}, timeout=60)
        return self._body(response, "auth")["jwe"]

    @staticmethod
    def _body(response, what):
        # Тело ответа - только в перехваченный вывод (зашифрованный журнал), в публичный журнал идёт лишь код
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 300 or data.get("code") != "OK":
            print(response.text)
            raise RuStoreError(f"{what}: HTTP {response.status_code}")
        return data.get("body")

    def _app(self, suffix=""):
        return f"{BASE}/public/v1/application/{self.package}/version{suffix}"

    def versions(self):
        """Версии приложения: список словарей с versionId, versionName, versionCode, versionStatus."""
        body = self._body(self.http.get(self._app(), params={"size": 50}, timeout=60), "versions")
        return body.get("content", []) if isinstance(body, dict) else (body or [])

    def newest(self):
        """Версия с наибольшим versionCode или None."""
        return max((v for v in self.versions() if v.get("versionCode")), key=lambda v: int(v["versionCode"]), default=None)

    @staticmethod
    def availability(version):
        return 1.0 if str(version.get("versionStatus", "")).upper() in LIVE else 0.0

    def submit(self, apk, version_code, notes):
        """Черновик версии, APK и отправка на модерацию; публикация сразу после неё (publishType INSTANTLY)."""
        existing = self.versions()
        if any(str(v.get("versionCode")) == str(version_code) and str(v.get("versionStatus", "")).upper() != "DRAFT" for v in existing):
            say(f"RuStore: version {version_code} is already submitted")
            return
        # Черновик не правится, только удаляется: брошенный прошлым прогоном уходит перед новым
        for draft in (v for v in existing if str(v.get("versionStatus", "")).upper() == "DRAFT"):
            self._body(self.http.delete(self._app(f"/{draft['versionId']}"), timeout=60), "draft delete")
        version_id = self._body(self.http.post(self._app(), json={"whatsNew": short_notes(notes, NOTES_LIMIT), "publishType": "INSTANTLY"},
                                               timeout=60), "draft create")
        with open(apk, "rb") as file:
            self._body(self.http.post(self._app(f"/{version_id}/apk"), params={"isMainApk": "true", "servicesType": "Unknown"},
                                      files={"file": (os.path.basename(apk), file, "application/vnd.android.package-archive")},
                                      timeout=1800), "apk upload")
        self._body(self.http.post(self._app(f"/{version_id}/commit"), params={"priorityUpdate": 0}, timeout=60), "commit")


def main():
    if len(sys.argv) != 4 or sys.argv[1] != "upload":
        fail("usage: rustore.py upload <app.apk> <update.json>")
    apk, update = sys.argv[2], load_update(sys.argv[3])
    store = RuStore(os.environ["RUSTORE_KEY_ID"].strip(), os.environ["RUSTORE_PRIVATE_KEY"], os.environ["APP_ID"])
    store.submit(apk, update["versionCode"], update.get("notes", ""))
    say(f"RuStore: {update['versionName']} ({update['versionCode']}) sent to review with auto-publish")


if __name__ == "__main__":
    main()
