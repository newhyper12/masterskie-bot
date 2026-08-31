# models.py
# Модели данных версии 2: SQLite как источник правды.

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Profile:
    telegram_id: int
    full_name: str
    group: str
    phone: str
    email: str
    nickname: str
    consent_date: str
    updated_at: str


@dataclass
class Workshop:
    id: int
    title: str
    format: str                 # 'базовая' | 'специальная'
    description: str
    date1: str                  # базовая: первая дата; специальная: дата старта
    date2: str = ""             # базовая: вторая дата (выбор при записи)
    location: str = ""
    lessons_count: int = 1
    days: str = ""
    quota: int = 0              # мест НА ОДНУ ДАТУ (базовая) или всего (спец.)
    photo: str = ""
    open_date: str = ""
    close_date: str = ""
    is_open: bool = False
    attendance_file_id: str | None = None
    deleted: bool = False


@dataclass
class Record:
    id: int
    telegram_id: int
    username: str
    workshop_id: int
    slot: int                   # 1 или 2 для базовых, 1 для специальных
    status: str                 # основной / резерв / отменено / отчислен
    created_at: str


@dataclass
class FormatInfo:
    name: str
    photo: str