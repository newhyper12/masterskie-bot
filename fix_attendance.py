#!/usr/bin/env python3
"""
Скрипт для восстановления связности файлов посещаемости с БД.
Использовать, если списки "обеспорядочились" после отмен/promote.

Запуск: python3 fix_attendance.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import load_settings
from db import DB
from attendance import AttendanceClient
from export import ExportClient


async def fix_attendance_for_workshop(
    w,
    db: DB,
    attendance: AttendanceClient,
    export: ExportClient,
):
    """Пересинхронизирует файл посещаемости с текущим состоянием БД."""
    print(f"\n{'='*60}")
    print(f"Обработка мастерской: {w.id}. {w.title}")
    print(f"{'='*60}")

    if not w.attendance_file_id:
        print("❌ Нет файла посещаемости, пропуск")
        return

    # Получаем активные записи из БД
    records = db.get_workshop_records(w.id, ["основной"])
    print(f"📊 Активных записей в БД: {len(records)}")

    # Группируем по slot (датам)
    records_by_slot = {}
    for r in records:
        if r.slot not in records_by_slot:
            records_by_slot[r.slot] = []
        records_by_slot[r.slot].append(r)

    for slot, slot_records in records_by_slot.items():
        date = w.date1 if slot == 1 else w.date2
        print(f"\n📅 Дата {slot}: {date}")
        print(f"   Записей: {len(slot_records)}")

        # Получаем текущее содержимое файла
        try:
            spreadsheet = attendance.gc.open_by_key(w.attendance_file_id)
            ws = attendance._target_sheet(spreadsheet, w, slot)
            values = ws.get_all_values()

            if not values or len(values) < 2:
                print("   ⚠️ Файл пуст или повреждён")
                continue

            # Подсчитываем непустые строки (заполненные участниками)
            filled_rows = 0
            for row in values[1:]:  # пропускаем заголовок
                if len(row) > 1 and row[1].strip():  # колонка ФИО не пустая
                    filled_rows += 1

            print(f"   Заполненных строк в файле: {filled_rows}")

            # Если количество не совпадает — предупреждаем
            if filled_rows != len(slot_records):
                print(f"   ⚠️ Несоответствие! В БД {len(slot_records)}, в файле {filled_rows}")

                # Спрашиваем, пересоздать ли файл
                answer = input(f"   Пересоздать файл посещаемости для этой даты? (y/n): ")
                if answer.lower() == 'y':
                    print("   🔄 Пересоздаю файл...")
                    try:
                        new_a_id = await attendance.rebuild_attendance(w)
                        db.update_workshop(w.id, attendance_file_id=new_a_id)
                        print(f"   ✅ Файл пересоздан: {new_a_id}")

                        # Добавляем всех участников заново
                        for r in slot_records:
                            p = db.get_profile(r.telegram_id)
                            if p:
                                await attendance.add_person(
                                    new_a_id, w, slot,
                                    p.full_name, p.group, p.nickname, p.telegram_id
                                )
                                print(f"   ✅ Добавлен: {p.full_name}")

                        # Обновляем таблицу участников
                        await export.export_one(w)
                        print("   ✅ Таблица участников обновлена")

                    except Exception as e:
                        print(f"   ❌ Ошибка при пересоздании: {e}")
                else:
                    print("   ⏭️ Пропуск")
            else:
                print("   ✅ Всё в порядке")

        except Exception as e:
            print(f"   ❌ Ошибка при чтении файла: {e}")


async def main():
    print("🔧 Восстановление связности файлов посещаемости")
    print("="*60)

    settings = load_settings()
    db = DB("bot.db")
    attendance = AttendanceClient(settings)
    export = ExportClient(settings, db)

    workshops = db.get_workshops(include_deleted=False)
    print(f"\nНайдено мастерских: {len(workshops)}")

    for w in workshops:
        await fix_attendance_for_workshop(w, db, attendance, export)

    print("\n" + "="*60)
    print("✅ Обработка завершена")


if __name__ == "__main__":
    asyncio.run(main())