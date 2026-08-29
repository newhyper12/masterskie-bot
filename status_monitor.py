# status_monitor.py
# Следит за правками оператора в файле «Записи»:
# - резерв -> основной: уведомление + перенос в файле посещаемости;
# - основной -> отчислен/отменено/удалена строка: уведомление + уборка;
# - автоматически открывает запись по дате.

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from attendance import AttendanceClient
from config import Settings
from records_client import RecordsClient
from sheets_client import SheetsClient
from texts import EXPELLED_TEXT, PROMOTED_TEXT


class StatusMonitor:
    def __init__(
        self,
        settings: Settings,
        sheets: SheetsClient,
        records: RecordsClient,
        attendance: AttendanceClient,
    ):
        self.settings = settings
        self.sheets = sheets
        self.records = records
        self.attendance = attendance

        # Сюда main.py передаст объект Bot для отправки сообщений.
        self.bot = None

        # Снимок состояния: {(telegram_id, workshop_id): статус}
        self.snapshot: dict[tuple[int, int], str] = {}
        self.opened_ids: set[int] = set()
        self.first_run = True
        self.closed_ids: set[int] = set()

    def set_known(self, telegram_id: int, workshop_id: int, status: str):
        """
        Вызывается ботом после собственных записей/отмен,
        чтобы монитор не принял их за правки оператора.
        """
        self.snapshot[(telegram_id, workshop_id)] = status

    async def run(self):
        """Бесконечный цикл мониторинга."""
        while True:
            try:
                await self._cycle()
            except Exception as e:
                # Монитор не должен ронять бота.
                print(f"[monitor] ошибка цикла: {e}")
            self.first_run = False
            await asyncio.sleep(self.settings.monitor_interval)

    # ==================================================
    # ОСНОВНОЙ ЦИКЛ
    # ==================================================

    async def _cycle(self):
        # Сначала освежаем кэш, потом сверяем статусы.
        await self.sheets.refresh()
        await self.records.refresh()
        await self._auto_open()
        rows = await self.records.get_all_records()
        current = {(r.telegram_id, r.workshop_id): r for r in rows}

        workshops = await self.sheets.get_workshops()
        wmap = {w.id: w for w in workshops}

        # Первый цикл — просто запоминаем состояние, без рассылок.
        if self.first_run:
            self.snapshot = {k: r.status for k, r in current.items()}
            return

        # 1) Оператор полностью удалил строку.
        for key, old_status in list(self.snapshot.items()):
            if key in current:
                continue
            tg_id, ws_id = key
            if old_status == "основной":
                await self._notify(tg_id, ws_id, wmap, EXPELLED_TEXT)
            await self._mirror(ws_id, wmap, tg_id, "removed")

        # 2) Оператор поменял статус.
        for key, rec in current.items():
            old = self.snapshot.get(key)
            if old is None or old == rec.status:
                continue

            tg_id, ws_id = key

            if old == "резерв" and rec.status == "основной":
                # То, ради чего всё затевалось: человека взяли в основу.
                await self._notify(tg_id, ws_id, wmap, PROMOTED_TEXT)
                await self._mirror(ws_id, wmap, tg_id, "to_main")

            elif old == "основной" and rec.status == "резерв":
                await self._mirror(ws_id, wmap, tg_id, "to_reserve")

            elif rec.status in ("отчислен", "отменено"):
                if old == "основной":
                    await self._notify(tg_id, ws_id, wmap, EXPELLED_TEXT)
                await self._mirror(ws_id, wmap, tg_id, "removed")

            elif old in ("отчислен", "отменено") and rec.status == "основной":
                # Оператор вернул человека в основу.
                await self._notify(tg_id, ws_id, wmap, PROMOTED_TEXT)
                await self._mirror(ws_id, wmap, tg_id, "to_main")

        # Обновляем снимок.
        self.snapshot = {k: r.status for k, r in current.items()}

    # ==================================================
    # СЛУЖЕБНОЕ
    # ==================================================

    async def _mirror(self, ws_id, wmap, tg_id, action: str):
        """Отражает изменение в файле посещаемости."""
        workshop = wmap.get(ws_id)
        if not workshop or not workshop.attendance_file_id:
            return
        try:
            if action == "removed":
                await self.attendance.remove_person(
                    workshop.attendance_file_id, tg_id
                )
            elif action == "to_main":
                await self.attendance.move_person(
                    workshop.attendance_file_id, tg_id, "основной"
                )
            elif action == "to_reserve":
                await self.attendance.move_person(
                    workshop.attendance_file_id, tg_id, "резерв"
                )
        except Exception as e:
            print(f"[monitor] ошибка зеркала: {e}")

    async def _notify(self, tg_id, ws_id, wmap, template: str):
        """Отправляет пользователю сообщение об изменении статуса."""
        if not self.bot:
            return
        workshop = wmap.get(ws_id)
        title = workshop.title if workshop else f"№{ws_id}"
        try:
            await self.bot.send_message(
                tg_id, template.format(title=title), parse_mode="HTML"
            )
        except Exception:
            # Например, пользователь заблокировал бота.
            pass

    async def _auto_open(self):
        """Автооткрытие и автозакрытие записи по расписанию."""
        workshops = await self.sheets.get_workshops()
        now = datetime.now()

        for w in workshops:
            close_passed = False
            if w.close_date:
                try:
                    close_passed = datetime.fromisoformat(w.close_date) <= now
                except ValueError:
                    pass

            # Автооткрытие (если время пришло и закрытие ещё не наступило).
            if w.id not in self.opened_ids and w.open_date and not close_passed:
                try:
                    open_dt = datetime.fromisoformat(w.open_date)
                except ValueError:
                    open_dt = None
                if (
                    open_dt
                    and open_dt <= now
                    and (now - open_dt) <= timedelta(days=1)
                ):
                    await self.sheets.set_registration_open(w.id, True)
                    self.opened_ids.add(w.id)
                    await self._notify_admin(
                        f"🔓 Запись на «{w.title}» открыта автоматически."
                    )

            # Автозакрытие.
            if w.id not in self.closed_ids and w.close_date:
                try:
                    close_dt = datetime.fromisoformat(w.close_date)
                except ValueError:
                    continue
                if close_dt <= now and (now - close_dt) <= timedelta(days=1):
                    await self.sheets.set_registration_open(w.id, False)
                    self.closed_ids.add(w.id)
                    await self._notify_admin(
                        f"🔒 Запись на «{w.title}» закрыта автоматически."
                    )

    async def _notify_admin(self, text: str):
        if not self.bot:
            return
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text)
            except Exception:
                pass