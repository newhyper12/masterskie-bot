# google_drive.py
# Работа с Google Диском: папка проекта, файлы таблиц, фотографии.

from __future__ import annotations

import io
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Права на работу с Диском.
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

# MIME-тип Google Таблицы при создании файла на Диске.
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"

# MIME-тип папки.
FOLDER_MIME = "application/vnd.google-apps.folder"


def get_sa_credentials(path: Path):
    """
    Создаёт credentials сервисного аккаунта из JSON-ключа.
    Используется ботом для работы с Диском.
    """
    return service_account.Credentials.from_service_account_file(
        str(path),
        scopes=DRIVE_SCOPES,
    )


def build_drive_service(credentials):
    """
    Собирает клиент Drive API из готовых credentials.

    На вход можно подать:
    - credentials сервисного аккаунта (get_sa_credentials);
    - credentials пользователя из gspread.oauth (gc.auth) — для init-скрипта.
    """
    return build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def get_sa_drive_service(path: Path):
    """Готовый Drive-клиент для сервисного аккаунта."""
    return build_drive_service(get_sa_credentials(path))


def create_folder(drive, title: str) -> str:
    """Создаёт папку на Диске и возвращает её ID."""
    body = {
        "name": title,
        "mimeType": FOLDER_MIME,
    }
    file = drive.files().create(body=body, fields="id").execute()
    return file["id"]


def create_spreadsheet_in_folder(drive, title: str, folder_id: str) -> str:
    """
    Создаёт пустую Google Таблицу внутри папки и возвращает её ID.
    Именно так бот будет создавать файлы посещаемости.
    """
    body = {
        "name": title,
        "mimeType": SPREADSHEET_MIME,
        "parents": [folder_id],
    }
    file = drive.files().create(body=body, fields="id").execute()
    return file["id"]


def share_file(
    drive,
    file_id: str,
    email: str,
    role: str = "writer",
) -> None:
    """
    Выдаёт доступ к файлу/папке.

    role="writer" — может редактировать (нужно сервисному аккаунту).
    """
    drive.permissions().create(
        fileId=file_id,
        body={
            "type": "user",
            "role": role,
            "emailAddress": email,
        },
        fields="id",
    ).execute()


def upload_file_bytes(
    drive,
    folder_id: str,
    name: str,
    data: bytes,
    mime_type: str = "image/jpeg",
) -> str:
    """
    Загружает файл (фото) в папку на Диске.
    Возвращает ID файла — его храним в таблице в колонке «фото».
    """
    media = MediaIoBaseUpload(
        io.BytesIO(data),
        mimetype=mime_type,
        resumable=False,
    )
    body = {
        "name": name,
        "parents": [folder_id],
    }
    file = drive.files().create(
        body=body,
        media_body=media,
        fields="id",
    ).execute()
    return file["id"]


def download_file_bytes(drive, file_id: str) -> bytes:
    """
    Скачивает файл с Диска по ID и возвращает байты.
    Используется, чтобы отправить фото из Диска в Telegram.
    """
    buffer = io.BytesIO()
    request = drive.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue()
