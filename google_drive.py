# google_drive.py
# Операции с Drive от имени твоего аккаунта (OAuth):
# папки, файлы, расшаривание сервис-аккаунту, удаление.

from __future__ import annotations

import json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def user_drive(settings):
    creds = Credentials.from_authorized_user_file(
        str(settings.oauth_token_file), SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def service_account_email(settings) -> str:
    with open(settings.service_account_file, encoding="utf-8") as f:
        return json.load(f)["client_email"]


def create_folder(drive, name: str, parent_id: str) -> str:
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    return drive.files().create(body=body, fields="id").execute()["id"]


def create_spreadsheet_in_folder(drive, title: str, folder_id: str) -> str:
    body = {
        "name": title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [folder_id],
    }
    return drive.files().create(body=body, fields="id").execute()["id"]


def share_with(drive, file_id: str, email: str, role: str = "writer"):
    drive.permissions().create(
        fileId=file_id,
        body={"type": "user", "role": role, "emailAddress": email},
        fields="id",
    ).execute()


def delete_file(drive, file_id: str):
    drive.files().delete(fileId=file_id).execute()