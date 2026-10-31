#!/usr/bin/env python3
"""Google Play Developer API: выкладка AAB в production долей 20% и чтение состояния дорожки (ci/store-status.py).

Учётная запись - сервисный аккаунт из секрета PLAY_SERVICE_ACCOUNT_JSON (его значение нигде не печатается). Нужен пакет google-auth
(.github/actions/store-tools). Пакет приложения - APP_ID из ci/build-tasks.env. Весь вывод скрипта перехватывает ci/quiet.sh.

Запуск (из каталога с распакованным пакетом):
    python3 ci/play.py upload <bundle.aab> <update.json>
В update.json - versionCode, versionName и notes релиза; заметки уходят в ru-RU и режутся до 500 знаков (предел Play).
"""
import contextlib
import json
import os
import sys

from store_common import fail, load_update, say, short_notes

API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
UPLOAD = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"
SCOPE = "https://www.googleapis.com/auth/androidpublisher"
TRACK = "production"
NOTES_LIMIT = 500
START_FRACTION = 0.2


class PlayError(RuntimeError):
    pass


class Play:
    def __init__(self, service_account_json, package):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(json.loads(service_account_json), scopes=[SCOPE])
        self.http = AuthorizedSession(credentials)
        self.package = package

    def _check(self, response, what):
        if response.status_code >= 300:
            # Тело ответа - только в перехваченный вывод (зашифрованный журнал), в публичный журнал идёт лишь код
            print(response.text)
            raise PlayError(f"{what}: HTTP {response.status_code}")
        return response.json() if response.content else {}

    @contextlib.contextmanager
    def edit(self):
        """Правка Play: создаётся, отдаётся как id; не закоммиченная - удаляется."""
        base = f"{API}/{self.package}/edits"
        edit_id = self._check(self.http.post(base, json={}), "edit insert")["id"]
        try:
            yield edit_id
        finally:
            self.http.delete(f"{base}/{edit_id}")

    def _commit(self, edit_id):
        # Коммит закрывает правку: последующее удаление в edit() вернёт 404 и ничего не испортит
        self._check(self.http.post(f"{API}/{self.package}/edits/{edit_id}:commit"), "edit commit")

    def production(self):
        """Самый новый выпуск дорожки production (по наибольшему versionCode) или None."""
        with self.edit() as edit_id:
            response = self.http.get(f"{API}/{self.package}/edits/{edit_id}/tracks/{TRACK}")
            if response.status_code == 404:
                return None
            releases = self._check(response, "track get").get("releases", [])
        releases = [r for r in releases if r.get("versionCodes")]
        return max(releases, key=lambda r: max(int(c) for c in r["versionCodes"]), default=None)

    def _upload_bundle(self, edit_id, path, version_code):
        with open(path, "rb") as bundle:
            response = self.http.post(f"{UPLOAD}/{self.package}/edits/{edit_id}/bundles?uploadType=media", data=bundle,
                                      headers={"Content-Type": "application/octet-stream"}, timeout=1800)
        if response.status_code in (400, 403) and "apkUpgradeVersionConflict" in response.text:
            # Повторный запуск после обрыва: пакет этой версии в Play уже есть - дальше только дорожка
            say(f"Play: bundle {version_code} is already uploaded")
            return
        self._check(response, "bundle upload")

    def _set_track(self, edit_id, release):
        url = f"{API}/{self.package}/edits/{edit_id}/tracks/{TRACK}"
        response = self.http.put(url, json={"track": TRACK, "releases": [release]})
        if response.status_code == 400 and "draft app" in response.text.lower():
            # Приложение в Play ещё черновик: API принимает только черновик выпуска, остальное владелец доделает в консоли
            say("::notice::Play: the app is still a draft, the release is saved as a draft: finish it in the Play Console")
            release = {key: value for key, value in release.items() if key != "userFraction"}
            release["status"] = "draft"
            response = self.http.put(url, json={"track": TRACK, "releases": [release]})
        self._check(response, "track update")

    def release(self, aab, version_code, version_name, notes):
        """Загрузить пакет и открыть выпуск в production долей START_FRACTION."""
        release = {"name": version_name, "versionCodes": [str(version_code)], "status": "inProgress", "userFraction": START_FRACTION,
                   "releaseNotes": [{"language": "ru-RU", "text": short_notes(notes, NOTES_LIMIT)}]}
        with self.edit() as edit_id:
            self._upload_bundle(edit_id, aab, version_code)
            self._set_track(edit_id, release)
            self._commit(edit_id)

    def promote(self, release):
        """Довести выпуск (как его вернул [production]) до 100%: статус completed, доли нет, заметки прежние."""
        done = {key: value for key, value in release.items() if key != "userFraction"}
        done["status"] = "completed"
        with self.edit() as edit_id:
            self._check(self.http.put(f"{API}/{self.package}/edits/{edit_id}/tracks/{TRACK}", json={"track": TRACK, "releases": [done]}),
                        "track promote")
            self._commit(edit_id)


def main():
    if len(sys.argv) != 4 or sys.argv[1] != "upload":
        fail("usage: play.py upload <bundle.aab> <update.json>")
    aab, update = sys.argv[2], load_update(sys.argv[3])
    play = Play(os.environ["PLAY_SERVICE_ACCOUNT_JSON"], os.environ["APP_ID"])
    play.release(aab, update["versionCode"], update["versionName"], update.get("notes", ""))
    say(f"Play: {update['versionName']} ({update['versionCode']}) sent to {TRACK} at {int(START_FRACTION * 100)}%")


if __name__ == "__main__":
    main()
