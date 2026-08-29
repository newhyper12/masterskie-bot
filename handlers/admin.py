# handlers/admin.py
# Админ-панель: создание мастерских, расписание записи, напоминания,
# фото приветствия.

from __future__ import annotations

import os
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from attendance import AttendanceClient
from config import Settings, update_env_value
from keyboards import (
    kb_admin_audience,
    kb_admin_format,
    kb_admin_menu,
    kb_admin_no_close,
    kb_admin_open_now,
    kb_admin_skip,
    kb_admin_workshops,
)
from models import Workshop
from records_client import RecordsClient
from sheets_client import SheetsClient
from states import (
    AdminReminderStates,
    AdminScheduleStates,
    AdminServiceStates,
    AdminWorkshopStates,
)
from texts import (
    ADMIN_ASK_CLOSE_AT,
    ADMIN_ASK_DATE,
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
    ADMIN_ASK_TITLE,
    ADMIN_MENU_TEXT,
    ADMIN_PHOTO_SET,
    ADMIN_SCHEDULE_SAVED,
    ADMIN_WORKSHOP_CREATED,
    REMINDER_SENT,
    reminder_text,
)

router = Router()


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return None


# ==================================================
# ВХОД В ПАНЕЛЬ
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
# МАСТЕР СОЗДАНИЯ МАСТЕРСКОЙ
# ==================================================

@router.callback_query(F.data == "admin:create")
async def cb_admin_create(
    callback: CallbackQuery, state: FSMContext, settings: Settings
):
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
async def cb_admin_format(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(format=callback.data.split(":", 1)[1])
    await state.set_state(AdminWorkshopStates.description)
    await callback.message.answer(ADMIN_ASK_DESCRIPTION)


@router.message(AdminWorkshopStates.description)
async def st_description(message: Message, state: FSMContext):
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminWorkshopStates.date)
    await message.answer(ADMIN_ASK_DATE)


@router.message(AdminWorkshopStates.date)
async def st_date(message: Message, state: FSMContext):
    await state.update_data(date=(message.text or "").strip())
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
    photo = message.photo[-1]
    await state.update_data(photo=photo.file_id)
    await state.set_state(AdminWorkshopStates.open_at)
    await message.answer(ADMIN_ASK_OPEN_AT, reply_markup=kb_admin_open_now())


@router.message(AdminWorkshopStates.photo)
async def st_photo_fallback(message: Message):
    await message.answer(
        "Пришли фото картинкой (не файлом) или нажми «Пропустить»."
    )


@router.callback_query(F.data == "skip:photo", AdminWorkshopStates.photo)
async def cb_skip_photo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(photo="")
    await state.set_state(AdminWorkshopStates.open_at)
    await callback.message.answer(
        ADMIN_ASK_OPEN_AT, reply_markup=kb_admin_open_now()
    )


# ---------- время открытия ----------

@router.message(AdminWorkshopStates.open_at)
async def st_open_at(message: Message, state: FSMContext):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer(
            "Не понял дату. Формат: ДД.ММ.ГГГГ ЧЧ:ММ, например 15.05.2026 16:00"
        )
        return
    await state.update_data(open_at_iso=dt.strftime("%Y-%m-%d %H:%M"))
    await state.set_state(AdminWorkshopStates.close_at)
    await message.answer(ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close())


@router.callback_query(F.data == "openat:now", AdminWorkshopStates.open_at)
async def cb_open_now(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(
        open_at_iso=datetime.now().strftime("%Y-%m-%d %H:%M"),
        is_open=True,
    )
    await state.set_state(AdminWorkshopStates.close_at)
    await callback.message.answer(
        ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close()
    )


# ---------- время закрытия ----------

@router.message(AdminWorkshopStates.close_at)
async def st_close_at(
    message: Message,
    state: FSMContext,
    sheets: SheetsClient,
    attendance: AttendanceClient,
):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer(
            "Не понял дату. Формат: ДД.ММ.ГГГГ ЧЧ:ММ, "
            "или нажми «Не закрывать»."
        )
        return
    await state.update_data(close_at_iso=dt.strftime("%Y-%m-%d %H:%M"))
    await _finish_create(message, state, sheets, attendance)


@router.callback_query(F.data == "noclose", AdminWorkshopStates.close_at)
async def cb_no_close(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: SheetsClient,
    attendance: AttendanceClient,
):
    await callback.answer()
    await state.update_data(close_at_iso="")
    await _finish_create(callback.message, state, sheets, attendance)


async def _finish_create(
    obj: Message,
    state: FSMContext,
    sheets: SheetsClient,
    attendance: AttendanceClient,
):
    data = await state.get_data()

    workshop_id = await sheets.get_next_workshop_id()
    workshop = Workshop(
        id=workshop_id,
        title=data.get("title", ""),
        format=data.get("format", "базовая"),
        description=data.get("description", ""),
        date=data.get("date", ""),
        location=data.get("location", ""),
        lessons_count=data.get("lessons", 1),
        days=data.get("days", ""),
        quota=data.get("quota", 0),
        photo=data.get("photo", ""),
        open_date=data.get("open_at_iso", ""),
        close_date=data.get("close_at_iso", ""),
        is_open=data.get("is_open", False),
        attendance_file_id=None,
    )

    try:
        file_id = await attendance.create(workshop)
    except Exception as e:
        await state.clear()
        await obj.answer(
            "⚠️ Не получилось создать файл посещаемости.\n"
            "Освободи место на Диске или обнови токен: "
            "python3 refresh_google_token.py"
        )
        await obj.answer(f"Детали: {str(e)[:200]}")
        await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())
        return

    workshop.attendance_file_id = file_id
    await sheets.create_workshop(workshop)
    await state.clear()

    open_human = "сейчас" if workshop.is_open else (workshop.open_date or "—")
    close_human = workshop.close_date or "не закрывается"
    await obj.answer(
        ADMIN_WORKSHOP_CREATED.format(title=workshop.title, open_at=open_human)
    )
    await obj.answer(f"🔒 Запись закроется: {close_human}")
    await obj.answer(
        "📄 Файл посещаемости (отправь преподавателю и оператору):\n"
        f"https://docs.google.com/spreadsheets/d/{file_id}"
    )
    await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# РАСПИСАНИЕ ЗАПИСИ (открытие/закрытие по датам)
# ==================================================

@router.callback_query(F.data == "admin:toggle")
async def cb_admin_toggle(
    callback: CallbackQuery, sheets: SheetsClient, settings: Settings
):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = await sheets.get_workshops()
    await callback.message.answer(
        "Выбери мастерскую — зададим время открытия и закрытия записи:",
        reply_markup=kb_admin_workshops(workshops, "sched"),
    )


@router.callback_query(F.data.startswith("sched:"))
async def cb_sched_ws(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminScheduleStates.open_at)
    await state.update_data(sched_ws=int(callback.data.split(":")[1]))
    await callback.message.answer(
        ADMIN_ASK_OPEN_AT, reply_markup=kb_admin_open_now()
    )


@router.message(AdminScheduleStates.open_at)
async def st_sched_open(message: Message, state: FSMContext):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer(
            "Не понял дату. Формат: ДД.ММ.ГГГГ ЧЧ:ММ, "
            "или нажми «Открыть сразу»."
        )
        return
    await state.update_data(sched_open=dt.strftime("%Y-%m-%d %H:%M"))
    await state.set_state(AdminScheduleStates.close_at)
    await message.answer(ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close())


@router.callback_query(F.data == "openat:now", AdminScheduleStates.open_at)
async def cb_sched_open_now(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(
        sched_open=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    await state.set_state(AdminScheduleStates.close_at)
    await callback.message.answer(
        ADMIN_ASK_CLOSE_AT, reply_markup=kb_admin_no_close()
    )


@router.message(AdminScheduleStates.close_at)
async def st_sched_close(
    message: Message, state: FSMContext, sheets: SheetsClient
):
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer(
            "Не понял дату. Формат: ДД.ММ.ГГГГ ЧЧ:ММ, "
            "или нажми «Не закрывать»."
        )
        return
    await _finish_schedule(
        message, state, sheets, dt.strftime("%Y-%m-%d %H:%M")
    )


@router.callback_query(F.data == "noclose", AdminScheduleStates.close_at)
async def cb_sched_no_close(
    callback: CallbackQuery, state: FSMContext, sheets: SheetsClient
):
    await callback.answer()
    await _finish_schedule(callback.message, state, sheets, "")


async def _finish_schedule(
    obj: Message, state: FSMContext, sheets: SheetsClient, close_iso: str
):
    data = await state.get_data()
    ws_id = data.get("sched_ws")
    open_iso = data.get("sched_open", "")

    await sheets.set_schedule(ws_id, open_iso, close_iso)
    await state.clear()

    workshop = await sheets.get_workshop_by_id(ws_id)
    title = workshop.title if workshop else f"№{ws_id}"
    await obj.answer(
        f"«{title}»: "
        + ADMIN_SCHEDULE_SAVED.format(
            open_at=open_iso or "—", close_at=close_iso or "не закрывается"
        )
    )
    await obj.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# ФОТО ПРИВЕТСТВИЯ
# ==================================================

@router.callback_query(F.data == "admin:setphoto")
async def cb_admin_setphoto(
    callback: CallbackQuery, state: FSMContext, settings: Settings
):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    await state.set_state(AdminServiceStates.start_photo)
    await callback.message.answer(ADMIN_ASK_SET_PHOTO)


@router.message(AdminServiceStates.start_photo, F.photo)
async def st_setphoto(message: Message, state: FSMContext):
    photo = message.photo[-1]
    update_env_value("START_PHOTO_ID", photo.file_id)
    os.environ["START_PHOTO_ID"] = photo.file_id
    await state.clear()
    await message.answer(ADMIN_PHOTO_SET)


# ==================================================
# НАПОМИНАНИЯ УЧАСТНИКАМ
# ==================================================

@router.callback_query(F.data == "admin:remind")
async def cb_admin_remind(
    callback: CallbackQuery, sheets: SheetsClient, settings: Settings
):
    if not _is_admin(callback.from_user.id, settings):
        return
    await callback.answer()
    workshops = await sheets.get_workshops()
    await callback.message.answer(
        "По какой мастерской напомнить?",
        reply_markup=kb_admin_workshops(workshops, "remindws"),
    )


@router.callback_query(F.data.startswith("remindws:"))
async def cb_remind_ws(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminReminderStates.audience)
    await state.update_data(remind_ws=int(callback.data.split(":")[1]))
    await callback.message.answer(
        "Кому отправить?", reply_markup=kb_admin_audience()
    )


@router.callback_query(F.data.startswith("aud:"), AdminReminderStates.audience)
async def cb_audience(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(audience=callback.data.split(":", 1)[1])
    await state.set_state(AdminReminderStates.text)
    await callback.message.answer(ADMIN_ASK_REMINDER_TEXT)


@router.message(AdminReminderStates.text)
async def st_reminder_text(
    message: Message,
    state: FSMContext,
    sheets: SheetsClient,
    records: RecordsClient,
):
    data = await state.get_data()
    ws_id = data.get("remind_ws")
    audience = data.get("audience", "все")
    body = (message.text or "").strip()

    workshop = await sheets.get_workshop_by_id(ws_id)
    if not workshop:
        await state.clear()
        await message.answer("Мастерская не найдена.")
        return

    if audience == "основной":
        statuses = ["основной"]
    elif audience == "резерв":
        statuses = ["резерв"]
    else:
        statuses = ["основной", "резерв"]

    targets = await records.get_workshop_records(ws_id, statuses)

    sent = 0
    for rec in targets:
        try:
            await message.bot.send_message(
                rec.telegram_id,
                reminder_text(workshop.title, body),
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            continue

    await state.clear()
    await message.answer(REMINDER_SENT.format(count=sent))
    await message.answer(ADMIN_MENU_TEXT, reply_markup=kb_admin_menu())


# ==================================================
# УТИЛИТА: file_id для любого фото от админа (вне состояний)
# ==================================================

@router.message(F.photo)
async def photo_file_id_utility(message: Message, settings: Settings):
    """
    Если админ шлёт фото вне мастеров — бот отвечает file_id.
    Удобно для заполнения листа «Форматы».
    """
    if not _is_admin(message.from_user.id, settings):
        return
    photo = message.photo[-1]
    await message.answer(f"file_id этого фото:\n<code>{photo.file_id}</code>")