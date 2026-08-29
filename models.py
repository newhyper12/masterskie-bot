# models.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class Profile:
    """Анкета пользователя."""
    telegram_id: int
    full_name: str
    group: str
    phone: str
    email: str
    nickname: str
    consent_date: str
    updated_at: str

@dataclass
class FormatInfo:
    """Формат мастерской (Базовый / Специальный)."""
    name: str          # базовая / специальная
    description: str
    photo: str         # ID файла на Google Диске

@dataclass
class Workshop:
    """Мастерская."""
    id: int
    title: str
    format: str        # базовая / специальная
    description: str
    date: str
    location: str
    lessons_count: int
    days: str
    quota: int
    photo: str         # ID файла на Google Диске
    open_date: Optional[str] # Дата/время открытия записи (строка из таблицы)
    is_open: bool      # Открыта ли запись вручную (да/нет)
    attendance_file_id: Optional[str] # ID файла посещаемости на Диске
    close_date: str = ""   # дата/время автозакрытия записи (ISO) или ""

@dataclass
class Record:
    """Запись пользователя на мастерскую."""
    telegram_id: int
    username: str      # @username в Telegram
    workshop_id: int
    status: str        # основной / резерв / отменено / отчислен
    created_at: str    # Дата и время записи
