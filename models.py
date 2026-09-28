# models.py
# Структуры данных бота.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Profile:
    telegram_id: int
    full_name: str = ""
    group: str = ""
    phone: str = ""
    email: str = ""
    nickname: str = ""
    consent_date: str = ""
    updated_at: str = ""
    birth_date: str = ""  # ДД.ММ.ГГГГ, пусто если не указана


@dataclass
class Workshop:
    id: int
    title: str = ""
    format: str = "базовая"          # базовая | специальная
    description: str = ""
    date1: str = ""
    date2: str = ""                  # только для базовой
    location: str = ""
    lessons_count: int = 1           # только для специальной
    days: str = ""                   # только для специальной
    quota: int = 0
    photo: str = ""
    open_date: str = ""              # ISO "YYYY-MM-DD HH:MM"
    close_date: str = ""
    is_open: bool = False
    attendance_file_id: str | None = None
    deleted: bool = False
    drive_folder_id: str | None = None
    participants_file_id: str | None = None


@dataclass
class Record:
    id: int
    telegram_id: int
    username: str = ""
    workshop_id: int = 0
    slot: int = 1                    # 1 = дата1, 2 = дата2
    status: str = "основной"         # основной | резерв | отменено
    created_at: str = ""


@dataclass
class FormatInfo:
    name: str
    photo: str = ""