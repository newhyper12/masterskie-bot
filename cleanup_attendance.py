# cleanup_attendance.py
# Убирает из файлов посещаемости всех, кто уже отменился.
import asyncio

from attendance import AttendanceClient
from config import load_settings
from db import DB


async def main():
    settings = load_settings()
    db = DB()
    att = AttendanceClient(settings)
    for r in db.all_records():
        if r.status != "отменено":
            continue
        w = db.get_workshop(r.workshop_id)
        if not w or not w.attendance_file_id:
            continue
        ok = await att.remove_person(
            w.attendance_file_id, w, r.slot, r.telegram_id
        )
        print(f"[{w.id}] {r.telegram_id}: {'убран' if ok else 'не найден'}")
    print("готово")


if __name__ == "__main__":
    asyncio.run(main())
