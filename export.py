# export.py
# v3: у каждой мастерской свой файл «список участников», который раз в минуту
# пересоздаётся из БД. Служебные колонки (по заголовкам) — перезаписываются,
# пользовательские (без заголовков из PARTICIPANTS_HEADERS) — сохраняются.
# Статусы ровно три: Активный / Резерв / Отменился.

from __future__ import annotations

import asyncio

import gspread

from attendance import PARTICIPANTS_HEADERS, col_letter
from config import Settings
from db import DB

STATUS_MAP = {
    "основной": "Активный",
    "резерв": "Резерв",
    "отменено": "Отменился",
    "отчислен": "Отменился",
}
STATUS_ORDER = {"Активный": 0, "Резерв": 1, "Отменился": 2}


class ExportClient:
    def __init__(self, settings: Settings, db: DB):
        self.db = db
        self.settings = settings
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )

    async def export_all(self):
        await asyncio.to_thread(self._sync_export)

    def _sync_export(self):
        for w in self.db.get_workshops(include_deleted=False):
            if not w.participants_file_id:
                continue
            try:
                self._sync_one(w)
            except Exception as e:
                print(f"[export] мастерская {w.id}: {e}")

    def _sync_one(self, w):
        records = [r for r in self.db.all_records() if r.workshop_id == w.id]
        records.sort(
            key=lambda r: (
                STATUS_ORDER.get(STATUS_MAP.get(r.status, "Отменился"), 3), r.id
            )
        )

        rows = [PARTICIPANTS_HEADERS]
        for r in records:
            p = self.db.get_profile(r.telegram_id)
            if w.format == "базовая":
                date = w.date1 if r.slot == 1 else (w.date2 or w.date1)
            else:
                date = w.date1
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

        ws = self.gc.open_by_key(w.participants_file_id).worksheet("Участники")
        existing = ws.get_all_values()
        header_idx = {h: i for i, h in enumerate(PARTICIPANTS_HEADERS)}
        user_cols = []
        if existing:
            first_row = existing[0]
            for i, cell in enumerate(first_row):
                if cell.strip() and cell not in header_idx:
                    user_cols.append(i)

        if user_cols and len(existing) > 1:
            saved = {}
            for r in existing[1:]:
                key = ""
                if len(r) > header_idx["telegram_id"]:
                    key = str(r[header_idx["telegram_id"]]).strip()
                if not key:
                    continue
                saved[key] = [r[i] if i < len(r) else "" for i in user_cols]
            for row in rows[1:]:
                key = str(row[0]).strip()
                extras = saved.get(key, [""] * len(user_cols))
                for idx, col in enumerate(user_cols):
                    while len(row) <= col:
                        row.append("")
                    row[col] = extras[idx] if idx < len(extras) else ""

        width = max(
            len(rows[0]),
            max(len(r) for r in rows) if len(rows) > 1 else 0,
        )
        padded = [r + [""] * (width - len(r)) for r in rows]
        ws.clear()
        ws.update(
            f"A1:{col_letter(width)}{len(padded)}",
            padded,
            value_input_option="USER_ENTERED",
        )