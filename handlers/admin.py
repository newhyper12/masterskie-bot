# handlers/admin.py
# Админ-панель v2: создание (с двумя датами и временем), расписание,
# редактирование, удаление с бэкапом, восстановление, фото, напоминания.

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from attendance import AttendanceClient
from config import Settings
from db import DB
from keyboards import (
    kb_admin_audience,
    kb_admin_edit_fields,
    kb_admin_format,
    kb_admin_menu,
    kb_admin_no_close,
    kb_admin_open_now,
    kb_admin_skip,
    kb_admin_workshops,
    kb_confirm_delete,
    kb_confirm_restore,
    kb_format_photo_pick,
)
from models import Workshop
from scheduler import Scheduler
from states import (
    AdminEditStates,
    AdminReminderStates,
    AdminScheduleStates,
    AdminServiceStates,
    AdminWorkshopStates,
)
from texts import (
    ADMIN_ASK_CLOSE_AT,
    ADMIN_ASK_DATE1,
    ADMIN_ASK_DATE2,
    ADMIN_ASK_DAYS,
    ADMIN_ASK_DESCRIPTION,
    ADMIN_ASK_FORMAT,
    ADMIN_ASK_LESSONS,
    ADMIN_ASK_LOCATION,
    ADMIN_ASK_OPEN_AT,
    ADMIN_ASK_PHOTO,
    ADMIN_ASK_QUOTA,
    ADMIN_ASK_REMINDER_TEXT,
    ADMIN_ASK_SET_PHOTO,
    ADMIN_ASK_START_TEXT,
    ADMIN_ASK_TITLE,
    ADMIN_BAD_DATE,
    ADMIN_MENU_TEXT,
    ADMIN_PHOTO_SET,
    ADMIN_SCHEDULE_SAVED,
    ADMIN_WORKSHOP_CREATED,
    DELETE_CONFIRM,
    DELETE_DONE,
    DELETE_PICK,
    EDIT_ASK_PHOTO,
    EDIT_ASK_VALUE,
    EDIT_DONE,
    EDIT_PICK,
    FORMAT_PHOTO_PICK,
    FORMAT_PHOTO_SET,
    REMINDER_SENT,
    RESTORE_DONE,
    RESTORE_NONE,
    RESTORE_PICK,
    START_TEXT_SET,
    reminder_text,
)

router = Router()

EDIT_LABELS = {
    "title": "название",
    "description": "описание",
    "date1": "дата 1",
    "date2": "дата 2",
    "location": "место",
    "quota": "квота",
}


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return None


def _parse_workshop_date(value: str) -> str | None:
    """Принимает ДД.ММ.ГГГГ или ДД.ММ.ГГГГ ЧЧ:ММ, возвращает нормализованную строку."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            if fmt == "%d.%m.%Y %H:%M":
                return dt.strftime("%d.%m.%Y %H:%M")
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    return None


# ==================================================
# ВХОД
# ==================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message, settings: Settings):
    if not _is_admin(message.from_user.id, settings):
        return
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


@router.callback_query(F.data == "admin:menu")
async def cb_admin_menu(callback: CallbackQuery, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# СОЗДАНИЕ МАСТЕРСКОЙ
# ==================================================

@router.callback_query(F.data == "admin:create")
async def cb_admin_create(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminWorkshopStates.title)
    await callback.message.answer(ADMIN_ASK_TITLE)


@router.message(AdminWorkshopStates.title)
async def st_title(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value:
        await message.answer(ADMIN_ASK_TITLE)
        return
    await state.update_data(title=value)
    await state.set_state(AdminWorkshopStates.format)
    await message.answer(ADMIN_ASK_FORMAT, reply_markup=kb_admin_format())


@router.callback_query(F.data.startswith("awfmt:"), AdminWorkshopStates.format)
async def cb_format(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(format=callback.data.split(":", 1)[1])
    await state.set_state(AdminWorkshopStates.description)
    await callback.message.answer(ADMIN_ASK_DESCRIPTION)


@router.message(AdminWorkshopStates.description)
async def st_description(message: Message, state: FSMContext):
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminWorkshopStates.date1)
    await message.answer(ADMIN_ASK_DATE1)


@router.message(AdminWorkshopStates.date1)
async def st_date1(message: Message, state: FSMContext):
    parsed = _parse_workshop_date(message.text or "")
    if parsed is None:
        await message.answer(ADMIN_BAD_DATE)
        return
    await state.update_data(date1=parsed)
    data = await state.get_data()
    if data.get("format") == "базовая":
        await state.set_state(AdminWorkshopStates.date2)
        await message.answer(ADMIN_ASK_DATE2)
    else:
        await state.update_data(date2="")
        await state.set_state(AdminWorkshopStates.location)
        await message.answer(ADMIN_ASK_LOCATION)


@router.message(AdminWorkshopStates.date2)
async def st_date2(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if value.lower() in ("нет", "-", "не", "no"):
        value = ""
    else:
        parsed = _parse_workshop_date(value)
        if parsed is None:
            await message.answer(ADMIN_BAD_DATE)
            return
        value = parsed
    await state.update_data(date2=value)
    await state.set_state(AdminWorkshopStates.location)
    await message.answer(ADMIN_ASK_LOCATION)


@router.message(AdminWorkshopStates.location)
async def st_location(message: Message, state: FSMContext):
    await state.update_data(location=(message.text or "").strip())
    data = await state.get_data()
    if data.get("format") == "специальная":
        await state.set_state(AdminWorkshopStates.lessons)
        await message.answer(ADMIN_ASK_LESSONS)
    else:
        await state.update_data(lessons=1, days="")
        await state.set_state(AdminWorkshopStates.quota)
        await message.answer(ADMIN_ASK_QUOTA)


@router.message(AdminWorkshopStates.lessons)
async def st_lessons(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value.isdigit() or int(value) < 1:
        await message.answer("Нужно число занятий (например, 4):")
        return
    await state.update_data(lessons=int(value))
    await state.set_state(AdminWorkshopStates.days)
    await message.answer(ADMIN_ASK_DAYS)


@router.message(AdminWorkshopStates.days)
async def st_days(message: Message, state: FSMContext):
    await state.update_data(days=(message.text or "").strip())
    await state.set_state(AdminWorkshopStates.quota)
    await message.answer(ADMIN_ASK_QUOTA)


@router.message(AdminWorkshopStates.quota)
async def st_quota(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value.isdigit() or int(value) < 1:
        await message.answer("Нужно число мест (например, 10):")
        return
    await state.update_data(quota=int(value))
    await state.set_state(AdminWorkshopStates.photo)
    await message.answer(ADMIN_ASK_PHOTO, reply_markup=kb_admin_skip("photo"))


@router.message(AdminWorkshopStates.photo, F.photo)
async def st_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(AdminWorkshopStates.open_at)
    await message.answer(ADMIN_ASK_OPEN_AT, reply_markup=kb_admin_open_now())


@router.message(AdminWorkshopStates.photo)
async def st_photo_fallback(message: Message):
    await message.answer("Пришли фото картинкой или нажми «Пропустить».")


@router.callback_query(F.data == "skip:photo", AdminWorkshopStates.photo)
async def cb_skip_photo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(photo="")
    await state.set_state(AdminWorkshopStates.open_at)
    await callback.message.answer(ADMIN_ASK_OPEN_AT, reply_markup=kb_admin_open_now())


@router.message(AdminWorkshopStates.open_at)
async def st_open_at(message: Message, state: FSMContext):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer("Формат: ДД.ММ.ГГГГ ЧЧ:ММ, или «⚡ Открыть сразу».")
        return
    await state.update_data(open_at_iso=dt.strftime("%Y-%m-%d %H:%M"))
    await state.set_state(AdminWorkshopStates.close_at)
    await message.answer(ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close())


@router.callback_query(F.data == "openat:now", AdminWorkshopStates.open_at)
async def cb_open_now(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(
        open_at_iso=datetime.now().strftime("%Y-%m-%d %H:%M"), is_open=True
    )
    await state.set_state(AdminWorkshopStates.close_at)
    await callback.message.answer(ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close())


@router.message(AdminWorkshopStates.close_at)
async def st_close_at(
    message: Message, state: FSMContext, db: DB, attendance: AttendanceClient
):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer("Формат: ДД.ММ.ГГГГ ЧЧ:ММ, или «Не закрывать».")
        return
    await state.update_data(close_at_iso=dt.strftime("%Y-%m-%d %H:%M"))
    await _finish_create(message, state, db, attendance)


@router.callback_query(F.data == "noclose", AdminWorkshopStates.close_at)
async def cb_no_close(
    callback: CallbackQuery, state: FSMContext, db: DB, attendance: AttendanceClient
):
    await callback.answer()
    await state.update_data(close_at_iso="")
    await _finish_create(callback.message, state, db, attendance)


async def _finish_create(obj: Message, state: FSMContext, db: DB, attendance: AttendanceClient):
    data = await state.get_data()
    now = datetime.now()

    open_iso = data.get("open_at_iso", "")
    close_iso = data.get("close_at_iso", "")
    is_open = data.get("is_open", False)
    if not is_open and open_iso:
        try:
            is_open = datetime.fromisoformat(open_iso) <= now
        except ValueError:
            pass
    if is_open and close_iso:
        try:
            if datetime.fromisoformat(close_iso) <= now:
                is_open = False
        except ValueError:
            pass

    workshop = Workshop(
        id=db.next_workshop_id(),
        title=data.get("title", ""),
        format=data.get("format", "базовая"),
        description=data.get("description", ""),
        date1=data.get("date1", ""),
        date2=data.get("date2", ""),
        location=data.get("location", ""),
        lessons_count=data.get("lessons", 1),
        days=data.get("days", ""),
        quota=data.get("quota", 0),
        photo=data.get("photo", ""),
        open_date=open_iso,
        close_date=close_iso,
        is_open=is_open,
        attendance_file_id=None,
    )

    print(f"[admin] создаю файл посещаемости для мастерской {workshop.id}...")
    try:
        workshop.attendance_file_id = await asyncio.wait_for(
            attendance.create(workshop), timeout=90
        )
    except asyncio.TimeoutError:
        await state.clear()
        await obj.answer(
            "⚠️ Google не ответил за 90 секунд при создании файла посещаемости. "
            "Попробуй создать мастерскую ещё раз."
        )
        await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return
    except Exception as e:
        await state.clear()
        await obj.answer(
            "⚠️ Не получилось создать файл посещаемости. "
            "Обнови токен: python3 refresh_google_token.py"
        )
        await obj.answer(f"Детали: {str(e)[:200]}")
        await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    print(f"[admin] файл создан: {workshop.attendance_file_id}")
    db.create_workshop(workshop)
    await state.clear()

    await obj.answer(
        ADMIN_WORKSHOP_CREATED.format(
            title=workshop.title, open_at=open_iso or "сейчас"
        )
    )
    await obj.answer(
        "📄 Файл посещаемости (отправь преподавателю):\n"
        f"https://docs.google.com/spreadsheets/d/{workshop.attendance_file_id}"
    )
    await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# РАСПИСАНИЕ ЗАПИСИ
# ==================================================

@router.callback_query(F.data == "admin:toggle")
async def cb_admin_toggle(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = db.get_workshops()
    await callback.message.answer(
        "Выбери мастерскую — зададим время открытия и закрытия:",
        reply_markup=kb_admin_workshops(workshops, "sched"),
    )


@router.callback_query(F.data.startswith("sched:"))
async def cb_sched_ws(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminScheduleStates.open_at)
    await state.update_data(sched_ws=int(callback.data.split(":")[1]))
    await callback.message.answer(ADMIN_ASK_OPEN_AT, reply_markup=kb_admin_open_now())


@router.message(AdminScheduleStates.open_at)
async def st_sched_open(message: Message, state: FSMContext):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer("Формат: ДД.ММ.ГГГГ ЧЧ:ММ, или «⚡ Открыть сразу».")
        return
    await state.update_data(sched_open=dt.strftime("%Y-%m-%d %H:%M"))
    await state.set_state(AdminScheduleStates.close_at)
    await message.answer(ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close())


@router.callback_query(F.data == "openat:now", AdminScheduleStates.open_at)
async def cb_sched_open_now(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(sched_open=datetime.now().strftime("%Y-%m-%d %H:%M"))
    await state.set_state(AdminScheduleStates.close_at)
    await callback.message.answer(ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close())


@router.message(AdminScheduleStates.close_at)
async def st_sched_close(message: Message, state: FSMContext, db: DB):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer("Формат: ДД.ММ.ГГГГ ЧЧ:ММ, или «Не закрывать».")
        return
    await _finish_schedule(message, state, db, dt.strftime("%Y-%m-%d %H:%M"))


@router.callback_query(F.data == "noclose", AdminScheduleStates.close_at)
async def cb_sched_no_close(callback: CallbackQuery, state: FSMContext, db: DB):
    await callback.answer()
    await _finish_schedule(callback.message, state, db, "")


async def _finish_schedule(obj: Message, state: FSMContext, db: DB, close_iso: str):
    data = await state.get_data()
    ws_id = data.get("sched_ws")
    open_iso = data.get("sched_open", "")

    now = datetime.now()
    is_open = False
    if open_iso:
        try:
            is_open = datetime.fromisoformat(open_iso) <= now
        except ValueError:
            pass
    if is_open and close_iso:
        try:
            if datetime.fromisoformat(close_iso) <= now:
                is_open = False
        except ValueError:
            pass

    db.update_workshop(ws_id, open_date=open_iso, close_date=close_iso, is_open=is_open)
    await state.clear()

    w = db.get_workshop(ws_id)
    await obj.answer(
        f"«{w.title if w else ws_id}»: "
        + ADMIN_SCHEDULE_SAVED.format(
            open_at=open_iso or "—", close_at=close_iso or "не закрывается"
        )
    )
    await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# РЕДАКТИРОВАНИЕ
# ==================================================

@router.callback_query(F.data == "admin:edit")
async def cb_admin_edit(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = db.get_workshops()
    await callback.message.answer(
        "Какую мастерскую редактируем?",
        reply_markup=kb_admin_workshops(workshops, "editws"),
    )


@router.callback_query(F.data.startswith("editws:"))
async def cb_editws(callback: CallbackQuery, state: FSMContext, db: DB):
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    await state.update_data(edit_ws=ws_id)
    w = db.get_workshop(ws_id)
    await callback.message.answer(
        EDIT_PICK.format(title=w.title if w else ws_id),
        reply_markup=kb_admin_edit_fields(ws_id),
    )


@router.callback_query(F.data.startswith("editf:"))
async def cb_editf(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, field, ws_raw = callback.data.split(":")
    ws_id = int(ws_raw)
    await state.update_data(edit_ws=ws_id, edit_field=field)
    if field == "photo":
        await state.set_state(AdminEditStates.photo)
        await callback.message.answer(EDIT_ASK_PHOTO)
    else:
        await state.set_state(AdminEditStates.value)
        await callback.message.answer(
            EDIT_ASK_VALUE.format(field=EDIT_LABELS.get(field, field))
        )


@router.message(AdminEditStates.value)
async def st_edit_value(message: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    field = data.get("edit_field", "title")
    ws_id = data.get("edit_ws")
    value = (message.text or "").strip()

    if field == "quota":
        if not value.isdigit() or int(value) < 1:
            await message.answer("Нужно положительное число.")
            return
        db.update_workshop(ws_id, quota=int(value))
    elif field in ("date1", "date2"):
        if field == "date2" and value.lower() in ("нет", "-", "не", "no"):
            db.update_workshop(ws_id, date2="")
        else:
            parsed = _parse_workshop_date(value)
            if parsed is None:
                await message.answer(ADMIN_BAD_DATE)
                return
            db.update_workshop(ws_id, **{field: parsed})
    else:
        db.update_workshop(ws_id, **{field: value})

    await state.clear()
    await message.answer(EDIT_DONE)
    w = db.get_workshop(ws_id)
    await message.answer(
        EDIT_PICK.format(title=w.title if w else ws_id),
        reply_markup=kb_admin_edit_fields(ws_id),
    )


@router.message(AdminEditStates.photo, F.photo)
async def st_edit_photo(message: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    ws_id = data.get("edit_ws")
    db.update_workshop(ws_id, photo=message.photo[-1].file_id)
    await state.clear()
    await message.answer(EDIT_DONE)
    w = db.get_workshop(ws_id)
    await message.answer(
        EDIT_PICK.format(title=w.title if w else ws_id),
        reply_markup=kb_admin_edit_fields(ws_id),
    )


# ==================================================
# УДАЛЕНИЕ И ВОССТАНОВЛЕНИЕ
# ==================================================

@router.callback_query(F.data == "admin:delete")
async def cb_admin_delete(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = db.get_workshops()
    await callback.message.answer(
        DELETE_PICK, reply_markup=kb_admin_workshops(workshops, "del")
    )


@router.callback_query(F.data.startswith("del:"))
async def cb_del(
    callback: CallbackQuery,
    db: DB,
    attendance: AttendanceClient,
    scheduler: Scheduler,
):
    await callback.answer()
    parts = callback.data.split(":")

    # выбрали мастерскую из списка — показываем подтверждение
    if len(parts) == 2:
        ws_id = int(parts[1])
        w = db.get_workshop(ws_id)
        if not w:
            return
        await callback.message.answer(
            DELETE_CONFIRM.format(title=w.title),
            reply_markup=kb_confirm_delete(ws_id),
        )
        return

    _, action, ws_raw = parts
    ws_id = int(ws_raw)
    w = db.get_workshop(ws_id)
    if not w:
        return

    if action == "no":
        await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    # свежий бэкап перед удалением
    try:
        await scheduler.backup_one(ws_id)
    except Exception as e:
        print(f"[backup] ошибка перед удалением: {e}")

    # удаляем файл с Диска
    if w.attendance_file_id:
        try:
            await attendance.delete_file(w.attendance_file_id)
        except Exception as e:
            print(f"[drive] не удалось удалить файл: {e}")

    db.update_workshop(ws_id, deleted=True, is_open=False)
    await callback.message.answer(DELETE_DONE.format(title=w.title))
    await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


@router.callback_query(F.data == "admin:restore")
async def cb_admin_restore(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    deleted = [
        w for w in db.get_workshops_raw(include_deleted=True)
        if w.deleted and db.has_backups(w.id)
    ]
    if not deleted:
        await callback.message.answer(RESTORE_NONE)
        return
    await callback.message.answer(
        RESTORE_PICK, reply_markup=kb_admin_workshops(deleted, "rest")
    )


@router.callback_query(F.data.startswith("rest:"))
async def cb_rest(
    callback: CallbackQuery, db: DB, attendance: AttendanceClient
):
    await callback.answer()
    parts = callback.data.split(":")

    # выбрали мастерскую из списка — показываем подтверждение
    if len(parts) == 2:
        ws_id = int(parts[1])
        w = db.get_workshop(ws_id)
        if not w:
            return
        await callback.message.answer(
            f"Восстановить «{w.title}» из последней резервной копии?",
            reply_markup=kb_confirm_restore(ws_id),
        )
        return

    _, action, ws_raw = parts
    ws_id = int(ws_raw)
    w = db.get_workshop(ws_id)
    if not w:
        return

    if action == "no":
        await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    backup = db.latest_backup(ws_id)
    new_file_id = None
    if backup and backup.get("attendance"):
        try:
            new_file_id = await attendance.restore(
                f"{w.title} — посещаемость", backup["attendance"]
            )
        except Exception as e:
            print(f"[restore] не удалось восстановить файл: {e}")
    if not new_file_id:
        try:
            new_file_id = await attendance.create(w)
        except Exception as e:
            print(f"[restore] не удалось создать файл: {e}")

    db.update_workshop(ws_id, deleted=False, attendance_file_id=new_file_id)
    await callback.message.answer(RESTORE_DONE.format(title=w.title))
    if new_file_id:
        await callback.message.answer(
            "📄 Новый файл посещаемости:\n"
            f"https://docs.google.com/spreadsheets/d/{new_file_id}"
        )
    await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# ФОТО ФОРМАТОВ / ПРИВЕТСТВИЯ / ТЕКСТ ПРИВЕТСТВИЯ
# ==================================================

@router.callback_query(F.data == "admin:fmtphoto")
async def cb_admin_fmtphoto(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await callback.message.answer(FORMAT_PHOTO_PICK, reply_markup=kb_format_photo_pick())


@router.callback_query(F.data.startswith("fmtphoto:"))
async def cb_fmtphoto_format(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(fmt_name=callback.data.split(":", 1)[1])
    await state.set_state(AdminServiceStates.format_photo)
    await callback.message.answer("Пришли фото для этого формата.")


@router.message(AdminServiceStates.format_photo, F.photo)
async def st_format_photo(message: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    name = data.get("fmt_name", "базовая")
    db.set_format_photo(name, message.photo[-1].file_id)
    await state.clear()
    await message.answer(FORMAT_PHOTO_SET.format(name=name))


@router.callback_query(F.data == "admin:setphoto")
async def cb_admin_setphoto(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminServiceStates.start_photo)
    await callback.message.answer(ADMIN_ASK_SET_PHOTO)


@router.message(AdminServiceStates.start_photo, F.photo)
async def st_setphoto(message: Message, state: FSMContext, db: DB):
    db.kv_set("START_PHOTO_ID", message.photo[-1].file_id)
    await state.clear()
    await message.answer(ADMIN_PHOTO_SET)


@router.callback_query(F.data == "admin:settext")
async def cb_admin_settext(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminServiceStates.start_text)
    await callback.message.answer(ADMIN_ASK_START_TEXT)


@router.message(AdminServiceStates.start_text)
async def st_settext(message: Message, state: FSMContext, db: DB):
    """
    Сохраняем текст ВМЕСТЕ с entities — так премиум-эмодзи,
    вставленные тобой, сохраняются и отображаются у пользователей.
    """
    keep = []
    for e in (message.entities or []):
        if e.type in ("custom_emoji", "bold", "italic", "underline"):
            d = {"type": e.type, "offset": e.offset, "length": e.length}
            if e.type == "custom_emoji":
                d["custom_emoji_id"] = e.custom_emoji_id
            keep.append(d)
    db.kv_set("START_MESSAGE", json.dumps(
        {"text": message.text or "", "entities": keep}, ensure_ascii=False
    ))
    await state.clear()
    await message.answer(START_TEXT_SET)


# ==================================================
# НАПОМИНАНИЯ
# ==================================================

@router.callback_query(F.data == "admin:remind")
async def cb_admin_remind(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = db.get_workshops()
    await callback.message.answer(
        "По какой мастерской напомнить?",
        reply_markup=kb_admin_workshops(workshops, "remindws"),
    )


@router.callback_query(F.data.startswith("remindws:"))
async def cb_remind_ws(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminReminderStates.audience)
    await state.update_data(remind_ws=int(callback.data.split(":")[1]))
    await callback.message.answer("Кому отправить?", reply_markup=kb_admin_audience())


@router.callback_query(F.data.startswith("aud:"), AdminReminderStates.audience)
async def cb_audience(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(audience=callback.data.split(":", 1)[1])
    await state.set_state(AdminReminderStates.text)
    await callback.message.answer(ADMIN_ASK_REMINDER_TEXT)


@router.message(AdminReminderStates.text)
async def st_reminder_text(message: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    ws_id = data.get("remind_ws")
    audience = data.get("audience", "все")
    body = (message.text or "").strip()

    w = db.get_workshop(ws_id)
    if not w:
        await state.clear()
        await message.answer("Мастерская не найдена.")
        return

    if audience == "основной":
        statuses = ["основной"]
    elif audience == "резерв":
        statuses = ["резерв"]
    else:
        statuses = ["основной", "резерв"]

    sent = 0
    for rec in db.get_workshop_records(ws_id, statuses):
        try:
            await message.bot.send_message(
                rec.telegram_id, reminder_text(w.title, body), parse_mode="HTML"
            )
            sent += 1
        except Exception:
            continue

    await state.clear()
    await message.answer(REMINDER_SENT.format(count=sent))
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# УТИЛИТА: file_id для фото вне состояний
# ==================================================

@router.message(F.photo)
async def photo_file_id_utility(message: Message, settings: Settings):
    if not _is_admin(message.from_user.id, settings):
        return
    await message.answer(
        f"file_id этого фото:\n<code>{message.photo[-1].file_id}</code>"
    )
