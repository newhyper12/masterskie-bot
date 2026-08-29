# config.py
# Загрузка настроек проекта из файла .env.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Папка проекта (где лежит этот файл).
BASE_DIR = Path(__file__).resolve().parent

# Путь к .env рядом с проектом.
ENV_PATH = BASE_DIR / ".env"


class ConfigError(Exception):
    """Ошибка конфигурации: нет обязательного параметра или файла."""
    pass


@dataclass
class Settings:
    """Все настройки приложения в одном месте."""

    # Токен бота. Для init-скрипта не обязателен, для бота — обязателен.
    bot_token: str | None

    # Telegram ID администраторов (несколько, через запятую в .env).
    admin_ids: set[int]

    # JSON-ключ сервисного аккаунта.
    service_account_file: Path

    # OAuth-клиент (нужен только init-скрипту).
    oauth_client_secret_file: Path

    # Куда сохраняется OAuth-токен после первой авторизации.
    oauth_token_file: Path

    # ID главной таблицы (Профили | Мастерские | Форматы).
    spreadsheet_id: str | None

    # Название главной таблицы.
    spreadsheet_title: str

    # ID папки на Диске, где лежат файлы мастерских.
    drive_folder_id: str | None

    # ID файла «Записи» (пользователь | мастерская | статус).
    records_spreadsheet_id: str | None

    # Как часто монитор проверяет правки оператора, в секундах.
    monitor_interval: int


def _get_path_from_env(env_name: str, default: str) -> Path:
    """Путь из .env; относительные пути считаем от папки проекта."""
    raw_value = os.getenv(env_name, "").strip() or default
    path = Path(raw_value)
    return path if path.is_absolute() else BASE_DIR / path


def load_settings(require_bot_token: bool = True) -> Settings:
    """
    Читает .env и собирает Settings.

    require_bot_token=False — для init-скрипта,
    require_bot_token=True — для запуска бота.
    """
    load_dotenv(ENV_PATH, override=False)

    bot_token = os.getenv("BOT_TOKEN", "").strip() or None
    if require_bot_token and not bot_token:
        raise ConfigError("Не задан BOT_TOKEN в файле .env.")

    # Читаем список админов: ADMIN_IDS=111,222,333
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
    admin_ids: set[int] = set()
    if admin_ids_raw:
        for part in admin_ids_raw.split(","):
            part = part.strip()
            if part.isdigit():
                admin_ids.add(int(part))

    interval_raw = os.getenv("MONITOR_INTERVAL", "").strip()
    monitor_interval = int(interval_raw) if interval_raw.isdigit() else 60

    return Settings(
        bot_token=bot_token,
        admin_ids=admin_ids,
        service_account_file=_get_path_from_env(
            "SERVICE_ACCOUNT_FILE", "service_account.json"
        ),
        oauth_client_secret_file=_get_path_from_env(
            "OAUTH_CLIENT_SECRET_FILE", "oauth_client_secret.json"
        ),
        oauth_token_file=_get_path_from_env(
            "OAUTH_TOKEN_FILE", "oauth_token.json"
        ),
        spreadsheet_id=os.getenv("SPREADSHEET_ID", "").strip() or None,
        spreadsheet_title=os.getenv(
            "SPREADSHEET_TITLE", "Мастерские — главная"
        ).strip(),
        drive_folder_id=os.getenv("DRIVE_FOLDER_ID", "").strip() or None,
        records_spreadsheet_id=(
            os.getenv("RECORDS_SPREADSHEET_ID", "").strip() or None
        ),
        monitor_interval=monitor_interval,
    )


def update_env_value(key: str, value: str) -> None:
    """Обновляет или добавляет переменную в .env."""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    found = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if stripped.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
