# models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
    format: str
    description: str
    date1: str
    date2: str
    location: str
    lessons_count: int
    days: str
    quota: int
    photo: str
    open_date: str
    close_date: str
    is_open: bool
    attendance_file_id: Optional[str] = None
    deleted: bool = False
    drive_folder_id: Optional[str] = None
    participants_file_id: Optional[str] = None


@dataclass
class Record:
    id: int
    telegram_id: int
    username: str
    workshop_id: int
    slot: int
    status: str
    created_at: str


@dataclass
class FormatInfo:
    name: str
    photo: str