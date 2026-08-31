# main.py
# Точка входа, версия 2: SQLite + фоновый планировщик.

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from attendance import AttendanceClient
from config import load_settings
from db import DB
from export import ExportClient
from handlers import admin, start, survey, workshop
from migrate import migrate_if_needed
from scheduler import Scheduler


async def main():
    settings = load_settings()

    db = DB("bot.db")
    attendance = AttendanceClient(settings)
    export = ExportClient(settings, db)
    scheduler = Scheduler(settings, db, attendance, export)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.include_router(start.router)
    dp.include_router(survey.router)
    dp.include_router(workshop.router)
    dp.include_router(admin.router)

    dp.workflow_data.update(
        settings=settings,
        db=db,
        attendance=attendance,
        export=export,
        scheduler=scheduler,
    )

    async def on_startup():
        scheduler.bot = bot
        await migrate_if_needed(settings, db)
        asyncio.create_task(scheduler.run())
        print("Бот запущен (v2, SQLite). Планировщик работает.")

    async def on_shutdown():
        await bot.session.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())