# migrate.py
# Одноразовый перенос данных из старых Google-таблиц в SQLite.

from __future__ import annotations

import asyncio

import gspread

from config import Settings
from db import DB
from models import Profile, Record, Workshop


async def migrate_if_needed(settings: Settings, db: DB):
    if db.kv_get("migrated_v2"):
        return
    try:
        await asyncio.to_thread(_migrate_sync, settings, db)
        db.kv_set("migrated_v2", "1")
        print("[migrate] данные перенесены из таблиц в БД")
    except Exception as e:
        print(f"[migrate] ошибка миграции (БД останется пустой): {e}")


def _migrate_sync(settings: Settings, db: DB):
    gc = gspread.service_account(filename=str(settings.service_account_file))

    # ---------- профили ----------
    main = gc.open_by_key(settings.spreadsheet_id)
    try:
        for row in main.worksheet("Профили").get_all_records():
            try:
                tg = int(row["telegram_id"])
            except (KeyError, ValueError):
                continue
            db.save_profile(Profile(
                telegram_id=tg,
                full_name=str(row.get("ФИО", "")),
                group=str(row.get("группа", "")),
                phone=str(row.get("телефон", "")),
                email=str(row.get("почта", "")),
                nickname=str(row.get("ник", "")),
                consent_date=str(row.get("согласие (дата)", "")),
                updated_at=str(row.get("обновлено", "")),
            ))
    except Exception as e:
        print(f"[migrate] профили: {e}")

    # ---------- мастерские ----------
    try:
        for row in main.worksheet("Мастерские").get_all_records():
            if not row.get("id"):
                continue
            try:
                quota = int(row.get("квота", 0))
            except (ValueError, TypeError):
                quota = 0
            try:
                lessons = int(row.get("кол-во занятий", 1))
            except (ValueError, TypeError):
                lessons = 1
            db.create_workshop(Workshop(
                id=int(row["id"]),
                title=str(row.get("название", "")),
                format=str(row.get("формат", "")).strip().lower(),
                description=str(row.get("описание", "")),
                date1=str(row.get("дата", "") or row.get("дата 1", "")),
                date2="",
                location=str(row.get("место", "")),
                lessons_count=lessons,
                days=str(row.get("дни проведения", "")),
                quota=quota,
                photo=str(row.get("фото", "")),
                open_date=str(row.get("открытие записи", "") or ""),
                close_date=str(row.get("закрытие записи", "") or ""),
                is_open=str(row.get("запись", "")).strip().lower() == "открыта",
                attendance_file_id=str(row.get("файл посещаемости", "")) or None,
            ))
    except Exception as e:
        print(f"[migrate] мастерские: {e}")

    # ---------- форматы (фото) ----------
    try:
        for row in main.worksheet("Форматы").get_all_records():
            name = str(row.get("формат", "")).strip().lower()
            if name:
                db.set_format_photo(name, str(row.get("фото", "")))
    except Exception as e:
        print(f"[migrate] форматы: {e}")

    # ---------- записи ----------
    try:
        rec_ws = gc.open_by_key(settings.records_spreadsheet_id).worksheet("Записи")
        for row in rec_ws.get_all_records():
            try:
                db.add_record(Record(
                    id=0,
                    telegram_id=int(row["telegram_id"]),
                    username=str(row.get("пользователь", "")),
                    workshop_id=int(row["мастерская"]),
                    slot=1,
                    status=str(row.get("статус", "")).strip().lower(),
                    created_at=str(row.get("дата записи", "")),
                ))
            except (KeyError, ValueError):
                continue
    except Exception as e:
        print(f"[migrate] записи: {e}")