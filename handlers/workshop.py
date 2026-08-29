# handlers/workshop.py
# Воронка записи: форматы -> мастерские -> карточка -> запись/резерв.
# Плюс «Мои записи» и отмена записи.

from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from attendance import AttendanceClient
from keyboards import (
    kb_cancel_confirm,
    kb_formats,
    kb_my_records,
    kb_reserve,
    kb_start,
    kb_workshop_card,
    kb_workshops,
)
from models import Profile, Record, Workshop
from records_client import RecordsClient
from sheets_client import SheetsClient
from texts import (
    ALREADY_SIGNED,
    ASK_CANCEL,
    CANCEL_DONE,
    CHOOSE_FORMAT,
    CHOOSE_WORKSHOP,
    MY_RECORDS_EMPTY,
    MY_RECORDS_TITLE,
    NO_WORKSHOPS,
    QUOTA_FULL,
    RESERVE_DONE,
    RESERVE_NO,
    SIGNED_MAIN,
    my_record_line,
    workshop_card_text,
    GOOGLE_RETRY,
)

router = Router()


# ==================================================
# СЛУЖЕБНОЕ
# ==================================================

async def _try_send_photo(
    message: Message,
    photo_id: str,
    text: str,
    reply_markup=None,
) -> bool:
    """
    Пытается отправить сообщение с фото по file_id.
    Возвращает True при успехе, False — если не получилось.
    """
    if not photo_id:
        return False
    try:
        await message.answer_photo(
            photo_id,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return True
    except Exception:
        return False


# ==================================================
# ПОКАЗ ЭКРАНОВ
# ==================================================

async def show_formats(message: Message, sheets: SheetsClient):
    """
    Выбор формата: ТОЛЬКО фото (медиагруппа без подписей)
    + фиксированные кнопки. Никакого текста.
    """
    formats = await sheets.get_formats()
    photos = {f.name: f.photo for f in formats if f.photo}

    media = []
    for name in ("базовая", "специальная"):
        if photos.get(name):
            media.append(InputMediaPhoto(media=photos[name]))

    if media:
        await message.answer_media_group(media)

    await message.answer(CHOOSE_FORMAT, reply_markup=kb_formats())


async def show_workshop_list(
    message: Message, sheets: SheetsClient, fmt: str
):
    """Список открытых мастерских выбранного формата."""
    workshops = await sheets.get_workshops(format_filter=fmt, only_open=True)
    if not workshops:
        formats = await sheets.get_formats()
        await message.answer(NO_WORKSHOPS, reply_markup=kb_formats())
        return
    await message.answer(CHOOSE_WORKSHOP, reply_markup=kb_workshops(workshops))


async def show_my_records(
    message: Message,
    user_id: int,
    sheets: SheetsClient,
    records: RecordsClient,
):
    """«Мои записи» с кнопками отмены."""
    user_records = await records.get_user_records(user_id)
    if not user_records:
        await message.answer(MY_RECORDS_EMPTY, reply_markup=kb_start())
        return

    workshops = await sheets.get_workshops()
    titles = {w.id: w.title for w in workshops}

    lines = [MY_RECORDS_TITLE, ""]
    rows = []
    for r in user_records:
        title = titles.get(r.workshop_id, f"Мастерская №{r.workshop_id}")
        lines.append(my_record_line(title, r.status))
        rows.append((r.workshop_id, title, r.status))

    await message.answer("\n".join(lines), reply_markup=kb_my_records(rows))


async def _do_register(
    message: Message,
    profile: Profile,
    workshop: Workshop,
    status: str,
    records: RecordsClient,
    attendance: AttendanceClient,
):
    """
    Фактическая запись: строка в файл «Записи»
    + человек в файле посещаемости.
    """
    record = Record(
        telegram_id=profile.telegram_id,
        username=profile.nickname,
        workshop_id=workshop.id,
        status=status,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Сначала пишем в Google. Если Google барахлит — честно говорим
    # пользователю повторить, и НЕ отправляем подтверждение.
    try:
        await records.add_record(record)
    except Exception as e:
        print(f"[records] не удалось сохранить запись: {e}")
        await message.answer(GOOGLE_RETRY)
        return

    # Сбой файла посещаемости не должен ронять запись:
    # главное — строка в «Записях», остальное поправим потом.
    if workshop.attendance_file_id:
        try:
            await attendance.add_person(
                workshop.attendance_file_id,
                profile.telegram_id,
                profile.full_name,
                profile.group,
                profile.nickname,
                status,
            )
        except Exception as e:
            print(f"[attendance] не удалось добавить человека: {e}")

    if status == "основной":
        await message.answer(SIGNED_MAIN.format(title=workshop.title))
    else:
        await message.answer(RESERVE_DONE.format(title=workshop.title))
# ==================================================
# КАЛЛБЭКИ ВОРОНКИ
# ==================================================

@router.callback_query(F.data.startswith("fmt:"))
async def cb_format(callback: CallbackQuery, sheets: SheetsClient):
    """Выбран формат — показываем мастерские."""
    await callback.answer()
    fmt = callback.data.split(":", 1)[1]
    await show_workshop_list(callback.message, sheets, fmt)


@router.callback_query(F.data == "back:formats")
async def cb_back_formats(callback: CallbackQuery, sheets: SheetsClient):
    """Возврат к выбору формата."""
    await callback.answer()
    await show_formats(callback.message, sheets)


@router.callback_query(F.data.startswith("ws:"))
async def cb_workshop_card(
    callback: CallbackQuery,
    sheets: SheetsClient,
    records: RecordsClient,
):
    """Карточка мастерской со свободными местами."""
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    workshop = await sheets.get_workshop_by_id(ws_id)
    if not workshop:
        await callback.message.answer("Мастерская не найдена.")
        return

    taken = await records.count_active_records(ws_id)
    free = max(workshop.quota - taken, 0)

    text = workshop_card_text(workshop, free)

    sent = await _try_send_photo(
        callback.message,
        workshop.photo,
        text,
        reply_markup=kb_workshop_card(ws_id),
    )
    if not sent:
        await callback.message.answer(
            text, reply_markup=kb_workshop_card(ws_id), parse_mode="HTML"
        )


@router.callback_query(F.data == "back:workshops")
async def cb_back_workshops(callback: CallbackQuery, sheets: SheetsClient):
    """Возврат к списку мастерских того же формата."""
    await callback.answer()
    formats = await sheets.get_formats()
    await callback.message.answer(CHOOSE_FORMAT, reply_markup=kb_formats())


@router.callback_query(F.data.startswith("signup:"))
async def cb_signup(
    callback: CallbackQuery,
    sheets: SheetsClient,
    records: RecordsClient,
    attendance: AttendanceClient,
):
    """Кнопка «Записаться»."""
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    workshop = await sheets.get_workshop_by_id(ws_id)
    if not workshop:
        await callback.message.answer("Мастерская не найдена.")
        return

    if not workshop.is_open:
        await callback.message.answer("Запись на эту мастерскую не открыта.")
        return

    tg_id = callback.from_user.id

    # Защита от двойной записи.
    existing = await records.get_user_record(tg_id, ws_id)
    if existing:
        await callback.message.answer(
            ALREADY_SIGNED.format(status=existing.status)
        )
        return

    taken = await records.count_active_records(ws_id)
    free = max(workshop.quota - taken, 0)

    if free <= 0:
        # Квота заполнена — предлагаем резерв.
        await callback.message.answer(
            QUOTA_FULL.format(title=workshop.title),
            reply_markup=kb_reserve(ws_id),
        )
        return

    profile = await sheets.get_profile(tg_id)
    if not profile:
        await callback.message.answer(
            "Сначала заполни анкету.", reply_markup=kb_start()
        )
        return

    await _do_register(
        callback.message, profile, workshop, "основной", records, attendance
    )


@router.callback_query(F.data.startswith("reserve:"))
async def cb_reserve(
    callback: CallbackQuery,
    sheets: SheetsClient,
    records: RecordsClient,
    attendance: AttendanceClient,
):
    """Ответ на вопрос «Хотите в резерв?»."""
    await callback.answer()
    _, answer, ws_id_raw = callback.data.split(":")
    ws_id = int(ws_id_raw)
    workshop = await sheets.get_workshop_by_id(ws_id)
    if not workshop:
        return

    if answer == "no":
        await callback.message.answer(RESERVE_NO)
        return

    tg_id = callback.from_user.id
    existing = await records.get_user_record(tg_id, ws_id)
    if existing:
        await callback.message.answer(
            ALREADY_SIGNED.format(status=existing.status)
        )
        return

    profile = await sheets.get_profile(tg_id)
    if not profile:
        return

    await _do_register(
        callback.message, profile, workshop, "резерв", records, attendance
    )


# ==================================================
# МОИ ЗАПИСИ И ОТМЕНА
# ==================================================

@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(
    callback: CallbackQuery,
    sheets: SheetsClient,
    records: RecordsClient,
    attendance: AttendanceClient,
):
    """Отмена записи: подтверждение и сама отмена."""
    await callback.answer()
    _, action, ws_id_raw = callback.data.split(":")
    ws_id = int(ws_id_raw)
    workshop = await sheets.get_workshop_by_id(ws_id)
    if not workshop:
        return

    if action == "ask":
        await callback.message.answer(
            ASK_CANCEL.format(title=workshop.title),
            reply_markup=kb_cancel_confirm(ws_id),
        )
        return

    if action == "no":
        await show_my_records(
            callback.message, callback.from_user.id, sheets, records
        )
        return

    # action == "yes": отменяем запись.
    await records.update_status(callback.from_user.id, ws_id, "отменено")
    if workshop.attendance_file_id:
        try:
            await attendance.remove_person(
                workshop.attendance_file_id, callback.from_user.id
            )
        except Exception as e:
            print(f"[attendance] не удалось убрать человека: {e}")

    await callback.message.answer(CANCEL_DONE.format(title=workshop.title))
    await show_my_records(
        callback.message, callback.from_user.id, sheets, records
    )