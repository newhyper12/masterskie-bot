# init_google_table.py
# Одноразовая инициализация Google-инфраструктуры проекта.

from __future__ import annotations

import json

import gspread
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from config import ConfigError, load_settings, update_env_value
from google_drive import (
    build_drive_service,
    create_folder,
    create_spreadsheet_in_folder,
    share_file,
)

# Права для OAuth: таблицы + диск.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ---------- Заголовки листов ----------

PROFILES_HEADERS = [
    "telegram_id",
    "ФИО",
    "группа",
    "телефон",
    "почта",
    "ник",
    "согласие (дата)",
    "обновлено",
]

WORKSHOPS_HEADERS = [
    "id",
    "название",
    "формат",
    "описание",
    "дата",
    "место",
    "кол-во занятий",
    "дни проведения",
    "квота",
    "фото",
    "открытие записи",
    "запись",
    "файл посещаемости",
]

FORMATS_HEADERS = [
    "формат",
    "описание",
    "фото",
]

RECORDS_HEADERS = [
    "telegram_id",
    "пользователь",
    "мастерская",
    "статус",
    "дата записи",
]

# ---------- Выпадающие списки ----------

STATUSES = ["основной", "резерв", "отменено", "отчислен"]
FORMATS = ["базовая", "специальная"]
REGISTRATION_STATES = ["открыта", "закрыта"]


def get_service_account_email(path) -> str:
    """Достаёт email сервисного аккаунта из JSON-ключа."""
    if not path.exists():
        raise ConfigError(
            f"Не найден файл сервисного аккаунта: {path}\n"
            "Скачай JSON-ключ в Google Cloud Console и положи его "
            "в папку проекта как service_account.json."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    email = data.get("client_email")
    if not email:
        raise ConfigError("В service_account.json нет client_email.")
    return email


def set_headers(worksheet, headers: list[str]) -> None:
    """Записывает заголовки в первую строку листа."""
    worksheet.resize(rows=1000, cols=max(len(headers), worksheet.col_count))
    for col, header in enumerate(headers, start=1):
        worksheet.update_cell(1, col, header)


def freeze_request(sheet_id: int) -> dict:
    """Закрепляет первую строку листа."""
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def dropdown_request(
    sheet_id: int,
    column_zero: int,
    values: list[str],
) -> dict:
    """Выпадающий список в колонке (начиная со 2-й строки)."""
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": 5000,
                "startColumnIndex": column_zero,
                "endColumnIndex": column_zero + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in values],
                },
                "showCustomUi": True,
                "strict": True,
            },
        }
    }


def main() -> None:
    settings = load_settings(require_bot_token=False)

    # Если всё уже создано — ничего не трогаем.
    if (
        settings.spreadsheet_id
        and settings.drive_folder_id
        and settings.records_spreadsheet_id
    ):
        print(
            "Инициализация уже выполнена:\n"
            f"главная таблица: {settings.spreadsheet_id}\n"
            f"папка: {settings.drive_folder_id}\n"
            f"записи: {settings.records_spreadsheet_id}\n\n"
            "Чтобы создать заново — очисти эти поля в .env."
        )
        return

    service_email = get_service_account_email(settings.service_account_file)

    # ---------- Авторизация ----------
    token_file = settings.oauth_token_file
    creds = None

    # Пробуем загрузить сохранённый токен
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            creds = None

    # Если токена нет или он невалиден — запускаем OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not settings.oauth_client_secret_file.exists():
                raise ConfigError(
                    f"Не найден OAuth-клиент: {settings.oauth_client_secret_file}"
                )
            print("Авторизация в Google...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.oauth_client_secret_file), SCOPES
            )
            # port=0 автоматически выберет свободный порт и откроет браузер
            creds = flow.run_local_server(port=0)
            
        # Сохраняем токен для следующих запусков
        token_file.write_text(creds.to_json(), encoding="utf-8")

    # Создаём клиенты на основе полученных credentials
    gc = gspread.authorize(creds)
    drive = build_drive_service(creds)

    # ---------- 1. Папка ----------
    folder_id = settings.drive_folder_id
    if not folder_id:
        print("Создаю папку «Мастерские (файлы)»...")
        folder_id = create_folder(drive, "Мастерские (файлы)")
        share_file(drive, folder_id, service_email, "writer")
        update_env_value("DRIVE_FOLDER_ID", folder_id)
        print(f"Папка создана: {folder_id}")

    # ---------- 2. Главная таблица ----------
    if not settings.spreadsheet_id:
        print("Создаю главную таблицу...")
        sh = gc.create(settings.spreadsheet_title)
        sh.share(service_email, perm_type="user", role="writer")

        profiles = sh.get_worksheet(0)
        profiles.update_title("Профили")
        workshops = sh.add_worksheet("Мастерские", rows=1000, cols=20)
        formats = sh.add_worksheet("Форматы", rows=100, cols=10)

        set_headers(profiles, PROFILES_HEADERS)
        set_headers(workshops, WORKSHOPS_HEADERS)
        set_headers(formats, FORMATS_HEADERS)

        requests = [
            freeze_request(profiles.id),
            freeze_request(workshops.id),
            freeze_request(formats.id),
            # «Мастерские»: формат — колонка C (индекс 2).
            dropdown_request(workshops.id, 2, FORMATS),
            # «Мастерские»: запись — колонка L (индекс 11).
            dropdown_request(workshops.id, 11, REGISTRATION_STATES),
        ]
        sh.batch_update({"requests": requests})

        update_env_value("SPREADSHEET_ID", sh.id)
        print(f"Главная таблица создана: {sh.url}")
    else:
        print("Главная таблица уже есть, пропускаю.")

    # ---------- 3. Файл «Записи» ----------
    if not settings.records_spreadsheet_id:
        print("Создаю файл «Записи» в папке...")
        records_id = create_spreadsheet_in_folder(
            drive, "Мастерские — записи", folder_id
        )
        share_file(drive, records_id, service_email, "writer")

        rec = gc.open_by_key(records_id)
        rec_ws = rec.get_worksheet(0)
        rec_ws.update_title("Записи")
        set_headers(rec_ws, RECORDS_HEADERS)

        rec.batch_update({
            "requests": [
                freeze_request(rec_ws.id),
                # статус — колонка D (индекс 3).
                dropdown_request(rec_ws.id, 3, STATUSES),
            ]
        })

        update_env_value("RECORDS_SPREADSHEET_ID", records_id)
        print(f"Файл «Записи» создан: {rec.url}")
    else:
        print("Файл «Записи» уже есть, пропускаю.")

    print(
        "\nГотово!\n\n"
        "Что дальше:\n"
        "1. Открой главную таблицу и заполни лист «Форматы»:\n"
        "   формат | описание | фото (Drive ID или пусто).\n"
        "2. Лист «Мастерские» пока не заполняй — мастерские будет\n"
        "   создавать админ прямо в боте.\n"
        "3. Запусти init ещё раз, чтобы убедиться, что всё сохранилось.\n"
    )


if __name__ == "__main__":
    main()
