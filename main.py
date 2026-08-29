# main.py
# main.py
# Точка входа: собирает бота, клиентов и фоновый монитор.

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from attendance import AttendanceClient
from config import load_settings
from drive_client import DriveClient
from handlers import admin, start, survey, workshop
from records_client import RecordsClient
from sheets_client import SheetsClient
from status_monitor import StatusMonitor


async def main():
    settings = load_settings(require_bot_token=True)

    # Бот с дефолтным parse_mode=HTML, чтобы не указывать его всюду.
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Клиенты для работы с Google.
    sheets = SheetsClient(settings)
    records = RecordsClient(settings)
    drive = DriveClient(settings)
    attendance = AttendanceClient(settings)

    # Фоновый монитор правок оператора.
    monitor = StatusMonitor(settings, sheets, records, attendance)

    # Когда бот сам меняет статусы, монитор узнаёт об этом сразу
    # и не считает это правкой оператора.
    records.on_known = monitor.set_known

    # Прокидываем объекты во все хендлеры.
    dp.workflow_data.update(
        settings=settings,
        sheets=sheets,
        records=records,
        drive=drive,
        attendance=attendance,
        monitor=monitor,
    )

    # Регистрируем роутеры. Порядок важен: start -> survey -> workshop -> admin.
    dp.include_router(start.router)
    dp.include_router(survey.router)
    dp.include_router(workshop.router)
    dp.include_router(admin.router)

    async def on_startup():
        monitor.bot = bot
        await sheets.ensure_workshop_columns()
        await sheets.refresh()
        await records.refresh()
        asyncio.create_task(monitor.run())
        print("Бот запущен. Кэш прогрет, монитор работает.")

    dp.startup.register(on_startup)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
