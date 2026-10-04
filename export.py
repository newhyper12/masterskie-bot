# export.py
# Авто-выгрузки (планировщик, раз в минуту):
#   1) файл «{название} — список участников» каждой мастерской;
#   2) общий отчёт «Мастерские — зарегистрированные люди» (уникальные люди,
#      с датой рождения). Таблица создаётся автоматически при первом цикле.
# Между экспортами паузы по 2 секунды — не упираемся в квоту Google Sheets.

from __future__ import annotations

import asyncio
import time

import gspread
from models import Workshop
from attendance import PARTICIPANTS_HEADERS, col_letter
from config import Settings
from db import DB
from google_drive import (
    create_spreadsheet_in_folder,
    service_account_email,
    share_with,
    user_drive,
)

PEOPLE_TITLE = "Мастерские — зарегистрированные люди"
PEOPLE_KV_KEY = "DUMP_PEOPLE_SPREADSHEET_ID"

STATUS_MAP = {
    "основной": "Активный",
    "резерв": "Резерв",
    "отменено": "Отменился",
    "отчислен": "Отменился",
}

PEOPLE_HEADERS = [
    "telegram_id", "ФИО", "Группа", "Дата рождения",
    "Телефон", "Почта", "Контакт", "Дата регистрации", "Записей на МК",
]

# Пауза между экспортами, чтобы не улетать в 429 Quota
INTER_EXPORT_SLEEP_SEC = 5


class ExportClient:
    def __init__(self, settings: Settings, db: DB):
        self.settings = settings
        self.db = db
        self.gc = gspread.service_account(filename=str(settings.service_account_file))

    async def export_all(self):
        await asyncio.to_thread(self._sync_export)

    async def export_one(self, w: Workshop):
        """НОВОЕ: Экспорт одной мастерской (немедленное обновление после отмены/promote)."""
        await asyncio.to_thread(self._export_workshop, w)

    def _sync_export(self):
        workshops = [
            w for w in self.db.get_workshops(include_deleted=False)
            if w.participants_file_id
        ]
        for w in workshops:
            try:
                self._export_workshop(w)
            except Exception as e:
                print(f"[export] мастерская {w.id}: {e}")
            time.sleep(INTER_EXPORT_SLEEP_SEC)

        try:
            self._export_people()
        except Exception as e:
            print(f"[export] отчёт людей: {e}")

    # --------------------------------------------------
    # файл участников мастерской
    # --------------------------------------------------

    def _export_workshop(self, w):
        rows = [PARTICIPANTS_HEADERS]
        records = self.db.get_workshop_records(
            w.id, ["основной", "резерв", "отменено"]
        )
        for r in records:
            p = self.db.get_profile(r.telegram_id)
            date = w.date1
            if w.format == "базовая" and r.slot == 2:
                date = w.date2 or w.date1
            rows.append([
                r.telegram_id,
                p.full_name if p else "",
                p.group if p else "",
                p.phone if p else "",
                p.email if p else "",
                p.nickname if p else "",
                date,
                STATUS_MAP.get(r.status, r.status),
                r.created_at,
            ])

        spreadsheet = self.gc.open_by_key(w.participants_file_id)
        try:
            ws = spreadsheet.worksheet("Участники")
        except Exception:
            ws = spreadsheet.get_worksheet(0)
            try:
                ws.update_title("Участники")
            except Exception:
                pass
        ws.clear()
        width = len(PARTICIPANTS_HEADERS)
        ws.update(
            f"A1:{col_letter(width)}{max(len(rows), 1)}",
            rows,
            value_input_option="USER_ENTERED",
        )

    # --------------------------------------------------
    # общий отчёт уникальных людей
    # --------------------------------------------------

    def _people_sheet_id(self) -> str:
        sid = self.db.kv_get(PEOPLE_KV_KEY)
        if sid:
            try:
                self.gc.open_by_key(sid)
                return sid
            except Exception:
                print(f"[export] таблица людей {sid} не найдена, создаю заново")
        drive = user_drive(self.settings)
        sa = service_account_email(self.settings)
        sid = create_spreadsheet_in_folder(
            drive, PEOPLE_TITLE, self.settings.drive_folder_id
        )
        share_with(drive, sid, sa)
        self.db.kv_set(PEOPLE_KV_KEY, sid)
        return sid

    def _export_people(self):
        sid = self._people_sheet_id()

        count_by_user = {}
        for r in self.db.all_records():
            if r.status in ("основной", "резерв"):
                count_by_user[r.telegram_id] = count_by_user.get(r.telegram_id, 0) + 1

        rows = [PEOPLE_HEADERS]
        for p in self.db.get_all_profiles():
            rows.append([
                p.telegram_id,
                p.full_name,
                p.group,
                p.birth_date or "",
                p.phone,
                p.email,
                p.nickname,
                p.updated_at,
                count_by_user.get(p.telegram_id, 0),
            ])

        spreadsheet = self.gc.open_by_key(sid)
        ws = spreadsheet.get_worksheet(0)
        try:
            ws.update_title("Люди")
        except Exception:
            pass
        ws.clear()
        width = len(PEOPLE_HEADERS)
        ws.update(
            f"A1:{col_letter(width)}{max(len(rows), 1)}",
            rows,
            value_input_option="USER_ENTERED",
        )
