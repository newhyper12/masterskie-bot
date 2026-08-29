# records_client.py
# Работа с файлом «Записи». Чтения — из кэша, записи — сразу в Google.

from __future__ import annotations

import asyncio
from typing import List, Optional

import gspread

from config import Settings
from models import Record

SHEET_RECORDS = "Записи"


class RecordsClient:
    def __init__(self, settings: Settings):
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )
        self.records_spreadsheet_id = settings.records_spreadsheet_id

        # Сюда монитор подставит свою функцию (см. main.py).
        self.on_known = None

        # ---------- кэш ----------
        self._records: List[Record] = []
        self._loaded = False

    def _get_sheet(self):
        return self.gc.open_by_key(
            self.records_spreadsheet_id
        ).worksheet(SHEET_RECORDS)

    # ==================================================
    # КЭШ
    # ==================================================

    async def refresh(self):
        """Перечитывает все строки «Записей» в память."""
        def _sync():
            rows = self._get_sheet().get_all_records()
            result = []
            for row in rows:
                try:
                    result.append(Record(
                        telegram_id=int(row["telegram_id"]),
                        username=str(row.get("пользователь", "")),
                        workshop_id=int(row["мастерская"]),
                        status=str(row.get("статус", "")).strip().lower(),
                        created_at=str(row.get("дата записи", "")),
                    ))
                except (KeyError, ValueError):
                    continue
            return result

        try:
            self._records = await asyncio.to_thread(_sync)
            self._loaded = True
        except Exception as e:
            print(f"[cache] не удалось обновить «Записи»: {e}")

    async def _ensure(self):
        if not self._loaded:
            await self.refresh()

    # ==================================================
    # ЧТЕНИЕ (из кэша)
    # ==================================================

    async def get_user_record(
        self, telegram_id: int, workshop_id: int
    ) -> Optional[Record]:
        await self._ensure()
        for r in self._records:
            if (r.telegram_id == telegram_id
                    and r.workshop_id == workshop_id
                    and r.status in ("основной", "резерв")):
                return r
        return None

    async def get_user_records(self, telegram_id: int) -> List[Record]:
        await self._ensure()
        return [
            r for r in self._records
            if r.telegram_id == telegram_id
            and r.status in ("основной", "резерв")
        ]

    async def count_active_records(self, workshop_id: int) -> int:
        await self._ensure()
        return sum(
            1 for r in self._records
            if r.workshop_id == workshop_id and r.status == "основной"
        )

    async def get_workshop_records(
        self, workshop_id: int, statuses: list
    ) -> List[Record]:
        await self._ensure()
        return [
            r for r in self._records
            if r.workshop_id == workshop_id and r.status in statuses
        ]

    async def get_all_records(self) -> List[Record]:
        await self._ensure()
        return list(self._records)

    # ==================================================
    # ЗАПИСЬ (сразу в Google + сразу в кэш)
    # ==================================================

    async def add_record(self, record: Record):
        def _sync():
            self._get_sheet().append_row([
                record.telegram_id,
                record.username,
                record.workshop_id,
                record.status,
                record.created_at,
            ])
        await asyncio.to_thread(_sync)

        self._records.append(record)

        if self.on_known:
            self.on_known(
                record.telegram_id, record.workshop_id, record.status
            )

    async def update_status(
        self, telegram_id: int, workshop_id: int, new_status: str
    ):
        def _sync():
            ws = self._get_sheet()
            rows = ws.get_all_records()
            for idx, row in enumerate(rows, start=2):
                if (str(row.get("telegram_id")) == str(telegram_id)
                        and str(row.get("мастерская")) == str(workshop_id)):
                    ws.update_cell(idx, 4, new_status)
                    break
        await asyncio.to_thread(_sync)

        for r in self._records:
            if r.telegram_id == telegram_id and r.workshop_id == workshop_id:
                r.status = new_status

        if self.on_known:
            self.on_known(telegram_id, workshop_id, new_status)
