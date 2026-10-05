# scheduler.py
# Фоновый цикл: авто-открытие/закрытие записи, экспорт файлов участников,
# почасовые резервные копии файлов посещаемости.

from __future__ import annotations

import asyncio
from datetime import datetime

from attendance import AttendanceClient
from config import Settings
from db import DB
from export import ExportClient

BACKUP_EVERY_SEC = 3600


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        db: DB,
        attendance: AttendanceClient,
        export: ExportClient,
    ):
        self.settings = settings
        self.db = db
        self.attendance = attendance
        self.export = export
        self.bot = None
        self._last_backup = 0.0

    async def run(self):
        while True:
            try:
                await self._cycle()
            except Exception as e:
                print(f"[scheduler] ошибка цикла: {e}")
            await asyncio.sleep(self.settings.monitor_interval)

    async def _cycle(self):
        await asyncio.to_thread(self._auto_open_close)
        await self.export.export_all()
        loop = asyncio.get_event_loop()
        if loop.time() - self._last_backup >= BACKUP_EVERY_SEC:
            await self.backup_all()
            self._last_backup = loop.time()

    # ---------- авто-открытие / закрытие ----------

    def _auto_open_close(self):
        now = datetime.now()
        for w in self.db.get_workshops_raw(include_deleted=False):
            new_open = w.is_open

            # Проверка открытия
            if not new_open and w.open_date:
                try:
                    open_dt = datetime.fromisoformat(w.open_date)
                except ValueError:
                    try:
                        open_dt = datetime.strptime(w.open_date, "%Y-%m-%d %H:%M")
                    except ValueError:
                        open_dt = None

                if open_dt and open_dt <= now:
                    new_open = True

            # Проверка закрытия
            if new_open and w.close_date:
                try:
                    close_dt = datetime.fromisoformat(w.close_date)
                except ValueError:
                    try:
                        close_dt = datetime.strptime(w.close_date, "%Y-%m-%d %H:%M")
                    except ValueError:
                        close_dt = None

                if close_dt and close_dt <= now:
                    new_open = False

            if new_open != w.is_open:
                self.db.update_workshop(w.id, is_open=new_open)
                status = "открыта" if new_open else "закрыта"
                print(f"[scheduler] мастерская {w.id} «{w.title}» {status}")


    async def backup_one(self, workshop_id: int):
        w = self.db.get_workshop(workshop_id)
        if not w:
            return
        dump = None
        if w.attendance_file_id:
            try:
                dump = await self.attendance.dump_attendance(w.attendance_file_id)
            except Exception as e:
                print(f"[backup] дампа нет: {e}")
        data = {"workshop": w.__dict__, "attendance": dump}
        await asyncio.to_thread(self.db.save_backup, workshop_id, data)

    async def backup_all(self):
        for w in self.db.get_workshops_raw(include_deleted=False):
            try:
                await self.backup_one(w.id)
            except Exception as e:
                print(f"[backup] {w.id}: {e}")
        print("[backup] резервные копии обновлены")