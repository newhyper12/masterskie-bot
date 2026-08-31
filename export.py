# export.py
# Автоэкспорт отчётов из БД в Google-таблицы.
# Таблицы больше не источник правды — это человекочитаемые отчёты.

from __future__ import annotations

import asyncio

import gspread

from config import Settings
from db import DB

RECORDS_HEADERS = [
    "telegram_id", "ФИО", "группа", "телефон", "почта", "контакт", "мастерские"
]
PROFILE_HEADERS = [
    "telegram_id", "ФИО", "группа", "телефон", "почта", "ник",
    "согласие (дата)", "обновлено"
]
WORKSHOP_HEADERS = [
    "id", "название", "формат", "описание", "дата 1", "дата 2", "место",
    "кол-во занятий", "дни проведения", "квота", "фото",
    "открытие записи", "закрытие записи", "запись", "файл посещаемости"
]


class ExportClient:
    def __init__(self, settings: Settings, db: DB):
        self.db = db
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )
        self.spreadsheet_id = settings.spreadsheet_id
        self.records_id = settings.records_spreadsheet_id

    async def export_all(self):
        """Пересоздаёт отчёты в таблицах из БД."""
        await asyncio.to_thread(self._sync_export)

    # ==================================================
    # ЗАПИСЬ В ЛИСТ С ПОВТОРОМ ПРИ ОБРЫВАХ
    # ==================================================

    def _write(self, spreadsheet_id: str, title: str, rows: list):
        ws = self.gc.open_by_key(spreadsheet_id).worksheet(title)
        ws.clear()
        ws.update(
            f"A1:{chr(64 + min(len(rows[0]), 26))}{len(rows)}",
            rows,
            value_input_option="USER_ENTERED",
        )

    def _safe_write(self, spreadsheet_id: str, title: str, rows: list) -> bool:
        for attempt in range(2):
            try:
                self._write(spreadsheet_id, title, rows)
                return True
            except Exception as e:
                print(
                    f"[export] «{title}» не обновилась (попытка {attempt + 1}): {e}"
                )
        return False

    # ==================================================
    # САМ ЭКСПОРТ
    # ==================================================

    def _sync_export(self):
        workshops = {w.id: w for w in self.db.get_workshops(include_deleted=True)}

        profiles = {}
        for rec in self.db.all_records():
            profiles.setdefault(rec.telegram_id, None)
        for tg in list(profiles):
            profiles[tg] = self.db.get_profile(tg)

        # ---------- отчёт «Записи»: строка на человека ----------
        by_user: dict[int, list] = {}
        for rec in self.db.all_records():
            if rec.status not in ("основной", "резерв"):
                continue
            by_user.setdefault(rec.telegram_id, []).append(rec)

        rows = [RECORDS_HEADERS]
        for tg, recs in sorted(by_user.items()):
            p = profiles.get(tg)
            entries = []
            for rec in recs:
                w = workshops.get(rec.workshop_id)
                if not w:
                    continue
                label = w.title
                if w.format == "базовая":
                    date = w.date1 if rec.slot == 1 else (w.date2 or w.date1)
                    if date:
                        label += f" ({date})"
                if rec.status == "резерв":
                    label += " — резерв"
                entries.append(label)
            rows.append([
                tg,
                p.full_name if p else "",
                p.group if p else "",
                p.phone if p else "",
                p.email if p else "",
                p.nickname if p else "",
                "; ".join(entries),
            ])

        self._safe_write(self.records_id, "Записи", rows)

        # ---------- главная таблица: Профили ----------
        prof_rows = [PROFILE_HEADERS]
        for tg, p in sorted(
            ((k, v) for k, v in profiles.items() if v),
            key=lambda kv: kv[0],
        ):
            prof_rows.append([
                p.telegram_id, p.full_name, p.group, p.phone, p.email,
                p.nickname, p.consent_date, p.updated_at,
            ])
        self._safe_write(self.spreadsheet_id, "Профили", prof_rows)

        # ---------- главная таблица: Мастерские ----------
        ws_rows = [WORKSHOP_HEADERS]
        for w in self.db.get_workshops(include_deleted=False):
            ws_rows.append([
                w.id, w.title, w.format, w.description, w.date1, w.date2,
                w.location, w.lessons_count, w.days, w.quota, w.photo,
                w.open_date, w.close_date,
                "открыта" if w.is_open else "закрыта",
                w.attendance_file_id or "",
            ])
        self._safe_write(self.spreadsheet_id, "Мастерские", ws_rows)