# scheduler.py
# Фоновый планировщик версии 2:
#  - автооткрытие/автозакрытие записи по датам;
#  - автоподъём резерва при освобождении места не здесь (в хендлерах);
#  - экспорт отчётов в Google-таблицы;
#  - почасовые резервные копии мастерских внутри БД.

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from datetime import datetime, timedelta

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
        self.interval = settings.monitor_interval
        self._last_backup = 0.0

    async def run(self):
        while True:
            try:
                await self._cycle()
            except Exception as e:
                print(f"[scheduler] ошибка цикла: {e}")
            await asyncio.sleep(self.interval)

    async def _cycle(self):
        await self._auto_open_close()
        await self.export.export_all()

        if time.monotonic() - self._last_backup > BACKUP_EVERY_SEC:
            await self.backup_all()
            self._last_backup = time.monotonic()

    # ==================================================
    # АВТО-ОТКРЫТИЕ / АВТО-ЗАКРЫТИЕ
    # ==================================================

    async def _auto_open_close(self):
        now = datetime.now()
        for w in self.db.get_workshops_raw():
            close_passed = False
            if w.close_date:
                try:
                    close_passed = datetime.fromisoformat(w.close_date) <= now
                except ValueError:
                    pass

            # автооткрытие
            if not w.is_open and w.open_date and not close_passed:
                try:
                    open_dt = datetime.fromisoformat(w.open_date)
                except ValueError:
                    open_dt = None
                if open_dt and open_dt <= now and (now - open_dt) <= timedelta(days=1):
                    self.db.update_workshop(w.id, is_open=True)
                    await self._notify(f"🔓 Запись на «{w.title}» открыта автоматически.")

            # автозакрытие
            if w.is_open and w.close_date:
                try:
                    close_dt = datetime.fromisoformat(w.close_date)
                except ValueError:
                    close_dt = None
                if close_dt and close_dt <= now and (now - close_dt) <= timedelta(days=1):
                    self.db.update_workshop(w.id, is_open=False)
                    await self._notify(f"🔒 Запись на «{w.title}» закрыта автоматически.")

    # ==================================================
    # РЕЗЕРВНЫЕ КОПИИ
    # ==================================================

    async def backup_all(self):
        for w in self.db.get_workshops_raw():
            if not w.attendance_file_id:
                continue
            try:
                dump = await self.attendance.dump(w.attendance_file_id)
            except Exception as e:
                print(f"[backup] не удалось снять дамп {w.id}: {e}")
                continue
            records = self.db.get_workshop_records(
                w.id, ["основной", "резерв", "отменено", "отчислен"]
            )
            self.db.save_backup(w.id, {
                "workshop": asdict(w),
                "records": [asdict(r) for r in records],
                "attendance": dump,
            })
        print("[backup] резервные копии обновлены")

    async def backup_one(self, workshop_id: int):
        w = self.db.get_workshop(workshop_id)
        if not w or not w.attendance_file_id:
            return
        dump = await self.attendance.dump(w.attendance_file_id)
        records = self.db.get_workshop_records(
            workshop_id, ["основной", "резерв", "отменено", "отчислен"]
        )
        self.db.save_backup(workshop_id, {
            "workshop": asdict(w),
            "records": [asdict(r) for r in records],
            "attendance": dump,
        })

    # ==================================================
    # УВЕДОМЛЕНИЯ АДМИНАМ
    # ==================================================

    async def _notify(self, text: str):
        if not self.bot:
            return
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text)
            except Exception:
                pass