# sheets_client.py
# Главная таблица: Профили, Форматы, Мастерские. Чтения — из кэша.

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import List, Optional

import gspread

from config import Settings
from models import FormatInfo, Profile, Workshop

SHEET_PROFILES = "Профили"
SHEET_WORKSHOPS = "Мастерские"
SHEET_FORMATS = "Форматы"


class SheetsClient:
    def __init__(self, settings: Settings):
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )
        self.spreadsheet_id = settings.spreadsheet_id

        self._profiles: dict[int, Profile] = {}
        self._formats: List[FormatInfo] = []
        self._workshops: List[Workshop] = []
        self._loaded = False

    def _get_sheet(self, title: str):
        return self.gc.open_by_key(self.spreadsheet_id).worksheet(title)

    # ==================================================
    # СЛУЖЕБНОЕ
    # ==================================================

    async def ensure_workshop_columns(self):
        """Добавляет колонку «закрытие записи», если её ещё нет."""
        def _sync():
            ws = self._get_sheet(SHEET_WORKSHOPS)
            headers = [str(h).strip().lower() for h in ws.row_values(1)]
            if "закрытие записи" not in headers:
                ws.update_cell(1, 14, "закрытие записи")
        await asyncio.to_thread(_sync)

    # ==================================================
    # КЭШ
    # ==================================================

    async def refresh(self):
        def _sync():
            profiles: dict[int, Profile] = {}
            for row in self._get_sheet(SHEET_PROFILES).get_all_records():
                try:
                    tg = int(row["telegram_id"])
                except (KeyError, ValueError):
                    continue
                profiles[tg] = Profile(
                    telegram_id=tg,
                    full_name=str(row.get("ФИО", "")),
                    group=str(row.get("группа", "")),
                    phone=str(row.get("телефон", "")),
                    email=str(row.get("почта", "")),
                    nickname=str(row.get("ник", "")),
                    consent_date=str(row.get("согласие (дата)", "")),
                    updated_at=str(row.get("обновлено", "")),
                )

            formats: List[FormatInfo] = []
            for row in self._get_sheet(SHEET_FORMATS).get_all_records():
                name = str(row.get("формат", "")).strip().lower()
                if not name:
                    continue
                formats.append(FormatInfo(
                    name=name,
                    description=str(row.get("описание", "")),
                    photo=str(row.get("фото", "")),
                ))

            workshops: List[Workshop] = []
            for row in self._get_sheet(SHEET_WORKSHOPS).get_all_records():
                if not row.get("id"):
                    continue
                try:
                    w_id = int(row["id"])
                except ValueError:
                    continue
                try:
                    quota = int(row.get("квота", 0))
                except (ValueError, TypeError):
                    quota = 0
                try:
                    lessons = int(row.get("кол-во занятий", 1))
                except (ValueError, TypeError):
                    lessons = 1

                open_raw = row.get("открытие записи")
                close_raw = row.get("закрытие записи")
                workshops.append(Workshop(
                    id=w_id,
                    title=str(row.get("название", "")),
                    format=str(row.get("формат", "")).strip().lower(),
                    description=str(row.get("описание", "")),
                    date=str(row.get("дата", "")),
                    location=str(row.get("место", "")),
                    lessons_count=lessons,
                    days=str(row.get("дни проведения", "")),
                    quota=quota,
                    photo=str(row.get("фото", "")),
                    open_date=str(open_raw) if open_raw else "",
                    close_date=str(close_raw) if close_raw else "",
                    is_open=(
                        str(row.get("запись", "")).strip().lower() == "открыта"
                    ),
                    attendance_file_id=(
                        str(row.get("файл посещаемости", "")) or None
                    ),
                ))
            return profiles, formats, workshops

        try:
            p, f, w = await asyncio.to_thread(_sync)
        except Exception as e:
            print(f"[cache] не удалось обновить главную таблицу: {e}")
            return

        self._profiles, self._formats, self._workshops = p, f, w
        self._loaded = True

    async def _ensure(self):
        if not self._loaded:
            await self.refresh()

    # ==================================================
    # ПРОФИЛИ
    # ==================================================

    async def get_profile(self, telegram_id: int) -> Optional[Profile]:
        await self._ensure()
        return self._profiles.get(telegram_id)

    async def save_profile(self, profile: Profile):
        def _sync():
            ws = self._get_sheet(SHEET_PROFILES)
            try:
                cell = ws.find(str(profile.telegram_id), in_column=1)
                if cell:
                    values = [[
                        profile.telegram_id, profile.full_name, profile.group,
                        profile.phone, profile.email, profile.nickname,
                        profile.consent_date, profile.updated_at,
                    ]]
                    ws.update(f"A{cell.row}:H{cell.row}", values)
                    return
            except gspread.exceptions.CellNotFound:
                pass
            ws.append_row([
                profile.telegram_id, profile.full_name, profile.group,
                profile.phone, profile.email, profile.nickname,
                profile.consent_date, profile.updated_at,
            ])
        await asyncio.to_thread(_sync)
        self._profiles[profile.telegram_id] = profile

    # ==================================================
    # ФОРМАТЫ
    # ==================================================

    async def get_formats(self) -> List[FormatInfo]:
        await self._ensure()
        return list(self._formats)

    # ==================================================
    # МАСТЕРСКИЕ
    # ==================================================

    async def get_workshops(
        self,
        format_filter: Optional[str] = None,
        only_open: bool = False,
    ) -> List[Workshop]:
        await self._ensure()
        now = datetime.now()
        result = []

        for w in self._workshops:
            if format_filter and w.format != format_filter.lower():
                continue

            # Открыта, если открыта вручную ИЛИ время открытия пришло.
            open_eff = w.is_open
            if not open_eff and w.open_date:
                try:
                    open_eff = datetime.fromisoformat(w.open_date) <= now
                except ValueError:
                    pass

            # Но закрыта, если время закрытия пришло.
            if open_eff and w.close_date:
                try:
                    if datetime.fromisoformat(w.close_date) <= now:
                        open_eff = False
                except ValueError:
                    pass

            if only_open and not open_eff:
                continue

            result.append(replace(w, is_open=open_eff))
        return result

    async def get_workshop_by_id(self, workshop_id: int) -> Optional[Workshop]:
        for w in await self.get_workshops():
            if w.id == workshop_id:
                return w
        return None

    async def get_next_workshop_id(self) -> int:
        await self._ensure()
        return max((w.id for w in self._workshops), default=0) + 1

    async def create_workshop(self, workshop: Workshop):
        def _sync():
            ws = self._get_sheet(SHEET_WORKSHOPS)
            ws.append_row([
                workshop.id, workshop.title, workshop.format,
                workshop.description, workshop.date, workshop.location,
                workshop.lessons_count, workshop.days, workshop.quota,
                workshop.photo, workshop.open_date,
                "открыта" if workshop.is_open else "закрыта",
                workshop.attendance_file_id or "",
                workshop.close_date,
            ])
        await asyncio.to_thread(_sync)
        self._workshops.append(workshop)

    async def set_registration_open(self, workshop_id: int, is_open: bool):
        def _sync():
            ws = self._get_sheet(SHEET_WORKSHOPS)
            cell = ws.find(str(workshop_id), in_column=1)
            if cell:
                ws.update_cell(cell.row, 12, "открыта" if is_open else "закрыта")
        await asyncio.to_thread(_sync)
        for w in self._workshops:
            if w.id == workshop_id:
                w.is_open = is_open

    async def set_schedule(
        self, workshop_id: int, open_iso: str, close_iso: str
    ):
        """Задаёт даты открытия и закрытия записи."""
        def _sync():
            ws = self._get_sheet(SHEET_WORKSHOPS)
            cell = ws.find(str(workshop_id), in_column=1)
            if not cell:
                return
            now = datetime.now()
            open_eff = False
            if open_iso:
                try:
                    open_eff = datetime.fromisoformat(open_iso) <= now
                except ValueError:
                    pass
            if open_eff and close_iso:
                try:
                    if datetime.fromisoformat(close_iso) <= now:
                        open_eff = False
                except ValueError:
                    pass
            ws.update_cell(cell.row, 11, open_iso)
            ws.update_cell(cell.row, 14, close_iso)
            ws.update_cell(cell.row, 12, "открыта" if open_eff else "закрыта")
        await asyncio.to_thread(_sync)

        for w in self._workshops:
            if w.id == workshop_id:
                w.open_date = open_iso
                w.close_date = close_iso