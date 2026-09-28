# handlers/admin.py
# Админ-панель v4: мастерские, расписание, редактирование с квотой,
# удаление/восстановление, фото, напоминания + НОВОЕ: рассылка всем.

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
    kb_birth_button,
    kb_confirm_delete,
    kb_confirm_restore,
    kb_format_photo_pick,
)
from models import Workshop
from scheduler import Scheduler
from states import (
    AdminBroadcastStates,
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
    BROADCAST_ASK_TEXT,
    BROADCAST_DONE,
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
# НОВОЕ: РАССЫЛКА ВСЕМ ЗАРЕГИСТРИРОВАННЫМ
# ==================================================

@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(
    callback: CallbackQuery, state: FSMContext, settings: Settings
):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminBroadcastStates.text)
    await callback.message.answer(BROADCAST_ASK_TEXT)


@router.message(AdminBroadcastStates.text)
async def st_broadcast_text(message: Message, state: FSMContext, db: DB):
    body = (message.text or "").strip()
    if not body:
        await message.answer(BROADCAST_ASK_TEXT)
        return
    await state.clear()

    profiles = db.get_all_profiles()
    sent = 0
    for p in profiles:
        try:
            await message.bot.send_message(
                p.telegram_id, body, reply_markup=kb_birth_button()
            )
            sent += 1
        except Exception:
            continue

    await message.answer(BROADCAST_DONE.format(sent=sent, total=len(profiles)))
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


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
        data = await state.get_data()
        if parsed == data.get("date1"):
            await message.answer("Вторая дата совпадает с первой. Введи другую дату или «Нет».")
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
        drive_folder_id=None,
        participants_file_id=None,
    )

    print(f"[admin] создаю рабочую область для мастерской {workshop.id}...")
    try:
        folder_id, p_id, a_id = await asyncio.wait_for(
            attendance.create_workspace(workshop), timeout=90
        )
        workshop.drive_folder_id = folder_id
        workshop.participants_file_id = p_id
        workshop.attendance_file_id = a_id
    except asyncio.TimeoutError:
        await state.clear()
        await obj.answer(
            "⚠️ Google не ответил за 90 секунд при создании рабочей области. "
            "Попробуй создать мастерскую ещё раз."
        )
        await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return
    except Exception as e:
        await state.clear()
        await obj.answer(
            "⚠️ Не получилось создать рабочую область. "
            "Обнови токен: python3 refresh_google_token.py"
        )
        await obj.answer(f"Детали: {str(e)[:200]}")
        await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    print(f"[admin] область создана: папка {folder_id}")
    db.create_workshop(workshop)
    await state.clear()

    await obj.answer(
        ADMIN_WORKSHOP_CREATED.format(title=workshop.title, open_at=open_iso or "сейчас")
    )
    await obj.answer(
        "📄 Список участников:\n"
        f"https://docs.google.com/spreadsheets/d/{workshop.participants_file_id}\n\n"
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
        await callback.message.answer(EDIT_ASK_VALUE.format(field=EDIT_LABELS[field]))


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


@router.message(AdminEditStates.photo)
async def st_edit_photo_fallback(message: Message):
    await message.answer("Пришли фото картинкой.")


@router.message(AdminEditStates.value)
async def st_edit_value(
    message: Message, state: FSMContext, db: DB, attendance: AttendanceClient
):
    data = await state.get_data()
    field = data.get("edit_field", "title")
    ws_id = data.get("edit_ws")
    value = (message.text or "").strip()

    if field == "quota":
        if not value.isdigit() or int(value) < 1:
            await message.answer("Нужно положительное число.")
            return
        new_quota = int(value)
        db.update_workshop(ws_id, quota=new_quota)

        busy = max(db.count_active(ws_id, 1), db.count_active(ws_id, 2))
        if new_quota < busy:
            await message.answer(
                f"⚠️ Новая квота {new_quota} меньше уже записанных ({busy}). "
                "Существующие участники останутся, но новые места не появятся, "
                "пока кто-то не отменит запись."
            )
        else:
            fresh = db.get_workshop(ws_id)
            if fresh and fresh.attendance_file_id:
                try:
                    await attendance.resize_quota(fresh)
                except Exception as e:
                    print(f"[admin] не удалось расширить файл посещаемости: {e}")
    elif field in ("date1", "date2"):
        if field == "date2" and value.lower() in ("нет", "-", "не", "no"):
            db.update_workshop(ws_id, date2="")
        else:
            parsed = _parse_workshop_date(value)
            if parsed is None:
                await message.answer(ADMIN_BAD_DATE)
                return
            fresh = db.get_workshop(ws_id)
            other = fresh.date2 if field == "date1" else fresh.date1
            if parsed == other and other:
                await message.answer("Даты не могут совпадать. Введи другую.")
                return
            db.update_workshop(ws_id, **{field: parsed})

        fresh = db.get_workshop(ws_id)
        if fresh and fresh.attendance_file_id:
            try:
                new_a_id = await attendance.rebuild_attendance(fresh)
                db.update_workshop(ws_id, attendance_file_id=new_a_id)
            except Exception as e:
                print(f"[admin] не удалось пересобрать посещаемость: {e}")
    else:
        db.update_workshop(ws_id, **{field: value})

    await state.clear()
    await message.answer(EDIT_DONE)
    w = db.get_workshop(ws_id)
    await message.answer(
        EDIT_PICK.format(title=w.title if w else ws_id),
        reply_markup=kb_admin_edit_fields(ws_id),
    )


# ==================================================
# УДАЛЕНИЕ / ВОССТАНОВЛЕНИЕ
# ==================================================

@router.callback_query(F.data == "admin:delete")
async def cb_admin_delete(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = db.get_workshops()
    if not workshops:
        await callback.message.answer("Нет активных мастерских.")
        return
    await callback.message.answer(
        DELETE_PICK, reply_markup=kb_admin_workshops(workshops, "delws")
    )


@router.callback_query(F.data.startswith("delws:"))
async def cb_delws(callback: CallbackQuery, state: FSMContext, db: DB):
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    await state.update_data(del_ws=ws_id)
    w = db.get_workshop(ws_id)
    await callback.message.answer(
        DELETE_CONFIRM.format(title=w.title if w else ws_id),
        reply_markup=kb_confirm_delete(ws_id),
    )


@router.callback_query(F.data.startswith("del:"))
async def cb_del(
    callback: CallbackQuery, state: FSMContext, db: DB, attendance: AttendanceClient
):
    await callback.answer()
    _, answer, ws_raw = callback.data.split(":")
    ws_id = int(ws_raw)
    await state.clear()
    if answer == "no":
        await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    w = db.get_workshop(ws_id)
    if not w:
        return

    dump = None
    if w.attendance_file_id:
        try:
            dump = await attendance.dump_attendance(w.attendance_file_id)
        except Exception as e:
            print(f"[admin] дамп перед удалением не снялся: {e}")
    if dump:
        db.save_backup(ws_id, dump)

    db.update_workshop(ws_id, deleted=True, is_open=False)
    try:
        await attendance.delete_workspace(w)
    except Exception as e:
        print(f"[admin] не удалось удалить рабочую область: {e}")

    await callback.message.answer(DELETE_DONE.format(title=w.title))
    await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


@router.callback_query(F.data == "admin:restore")
async def cb_admin_restore(callback: CallbackQuery, db: DB, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    deleted = db.get_workshops(include_deleted=True)
    deleted = [w for w in deleted if w.deleted]
    if not deleted:
        await callback.message.answer(RESTORE_NONE)
        return
    await callback.message.answer(
        RESTORE_PICK, reply_markup=kb_admin_workshops(deleted, "restws")
    )


@router.callback_query(F.data.startswith("restws:"))
async def cb_restws(callback: CallbackQuery, db: DB, attendance: AttendanceClient):
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    w = db.get_workshop(ws_id)
    if not w:
        return

    dump = db.latest_backup(ws_id)
    folder_id, p_id, a_id = await attendance.restore_workspace(w, dump)
    db.update_workshop(
        ws_id,
        deleted=False,
        drive_folder_id=folder_id,
        participants_file_id=p_id,
        attendance_file_id=a_id,
    )
    await callback.message.answer(RESTORE_DONE.format(title=w.title))
    await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# ФОТО ФОРМАТОВ / ПРИВЕТСТВИЕ
# ==================================================

@router.callback_query(F.data == "admin:fmtphoto")
async def cb_admin_fmtphoto(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminServiceStates.format_photo)
    await callback.message.answer(FORMAT_PHOTO_PICK, reply_markup=kb_format_photo_pick())


@router.callback_query(F.data.startswith("fmtphoto:"), AdminServiceStates.format_photo)
async def cb_fmtphoto_pick(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(fmt_name=callback.data.split(":", 1)[1])
    await callback.message.answer("Пришли фото картинкой.")


@router.message(AdminServiceStates.format_photo, F.photo)
async def st_fmt_photo(message: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    name = data.get("fmt_name", "базовая")
    db.set_format_photo(name, message.photo[-1].file_id)
    await state.clear()
    await message.answer(FORMAT_PHOTO_SET.format(name=name))
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


@router.message(AdminServiceStates.format_photo)
async def st_fmt_photo_fallback(message: Message):
    await message.answer("Пришли фото картинкой.")


@router.callback_query(F.data == "admin:setphoto")
async def cb_admin_setphoto(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminServiceStates.start_photo)
    await callback.message.answer(ADMIN_ASK_SET_PHOTO)


@router.message(AdminServiceStates.start_photo, F.photo)
async def st_start_photo(message: Message, state: FSMContext, db: DB):
    db.kv_set("START_PHOTO_ID", message.photo[-1].file_id)
    await state.clear()
    await message.answer(ADMIN_PHOTO_SET)
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


@router.message(AdminServiceStates.start_photo)
async def st_start_photo_fallback(message: Message):
    await message.answer("Пришли фото картинкой.")


@router.callback_query(F.data == "admin:settext")
async def cb_admin_settext(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminServiceStates.start_text)
    await callback.message.answer(ADMIN_ASK_START_TEXT)


@router.message(AdminServiceStates.start_text)
async def st_start_text(message: Message, state: FSMContext, db: DB):
    payload = {
        "text": message.text or message.caption or "",
        "entities": [e.model_dump() for e in (message.entities or message.caption_entities or [])],
    }
    db.kv_set("START_MESSAGE", json.dumps(payload, ensure_ascii=False))
    await state.clear()
    await message.answer(START_TEXT_SET)
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# НАПОМИНАНИЯ
# ==================================================

@router.callback_query(F.data == "admin:remind")
async def cb_admin_remind(callback: CallbackQuery, state: FSMContext, settings: Settings):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminReminderStates.audience)
    await callback.message.answer("Кому напомнить?", reply_markup=kb_admin_audience())


@router.callback_query(F.data.startswith("aud:"), AdminReminderStates.audience)
async def cb_aud(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(aud=callback.data.split(":", 1)[1])
    await state.set_state(AdminReminderStates.text)
    await callback.message.answer(ADMIN_ASK_REMINDER_TEXT)


@router.message(AdminReminderStates.text)
async def st_remind_text(message: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    aud = data.get("aud", "все")
    body = (message.text or "").strip()
    await state.clear()
    if not body:
        await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    targets = set()
    for w in db.get_workshops(include_deleted=True):
        statuses = ["основной"] if aud == "основной" else (
            ["резерв"] if aud == "резерв" else ["основной", "резерв"]
        )
        for r in db.get_workshop_records(w.id, statuses):
            targets.add(r.telegram_id)

    sent = 0
    for tid in targets:
        try:
            await message.bot.send_message(tid, reminder_text(body))
            sent += 1
        except Exception:
            continue

    await message.answer(REMINDER_SENT.format(sent=sent, total=len(targets)))
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())