# drive_client.py
# Работа с Google Диском: загрузка и скачивание фотографий.

from __future__ import annotations

import asyncio
import io

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from config import Settings

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Сервисный аккаунт с правами на Диск.
        self.credentials = service_account.Credentials.from_service_account_file(
            str(settings.service_account_file),
            scopes=DRIVE_SCOPES,
        )
        self.drive_service = build(
            "drive", "v3",
            credentials=self.credentials,
            cache_discovery=False,
        )

    async def upload_photo(self, photo_bytes: bytes, filename: str) -> str:
        """
        Загружает фото в папку проекта на Диске.
        Возвращает ID файла — его храним в таблице в колонке «фото».
        """
        def _sync():
            media = MediaIoBaseUpload(
                io.BytesIO(photo_bytes),
                mimetype="image/jpeg",
                resumable=False,
            )
            body = {
                "name": filename,
                "parents": [self.settings.drive_folder_id],
            }
            file = self.drive_service.files().create(
                body=body,
                media_body=media,
                fields="id",
            ).execute()
            return file["id"]

        return await asyncio.to_thread(_sync)

    async def download_photo(self, file_id: str) -> bytes:
        """Скачивает файл с Диска по ID и возвращает байты."""
        def _sync():
            buffer = io.BytesIO()
            request = self.drive_service.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            return buffer.getvalue()

        return await asyncio.to_thread(_sync)
