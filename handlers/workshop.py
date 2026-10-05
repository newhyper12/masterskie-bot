# handlers/workshop.py
# Воронка записи v3: FIFO + срок 1 час, реальный статус, компактные даты.
# Отмена освобождает строку в файле посещаемости.

from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from export import ExportClient
from attendance import AttendanceClient
from db import DB
from keyboards import (
    kb_cancel_confirm,
    kb_formats,
    kb_my_records,
    kb_promote_offer,
    kb_reserve,
    kb_slot_dates,
    kb_start,
    kb_workshop_card,
    kb_workshops,
)
from models import Profile, Record, Workshop
from texts import (
    ALREADY_SIGNED_REAL,
    ASK_CANCEL,
    ASK_SLOT,
    CANCEL_DONE,
    CHOOSE_FORMAT,
    CHOOSE_WORKSHOP,
    GOOGLE_RETRY,
    MY_RECORDS_EMPTY,
    MY_RECORDS_TITLE,
    NO_WORKSHOPS,
    PROMOTE_DECLINED,
    PROMOTE_EXPIRED,
    PROMOTE_OFFER,
    PROMOTE_YES,
    QUOTA_FULL,
    RESERVE_DONE,
    RESERVE_NO,
    SIGNED_MAIN,
    my_record_line,
    workshop_card_text,
)

router = Router()

PROMOTE_TTL_SEC = 3600  # предложение резервисту живёт 1 час


def _slot_date(w: Workshop, slot: int) -> str:
    if w.format == "базовая":
        if slot == 1:
            return w.date1 if w.date1 else "Дата уточняется"
        else:
            return w.date2 if w.date2 else "Дата уточняется"
    return w.date1 if w.date1 else "Дата уточняется"

def _status_label(status: str) -> str:
    return {"основной": "основной набор", "резерв": "резерв"}.get(status, status)

# ==================================================
# ЭКРАНЫ
# ==================================================

async def show_formats(message: Message, db: DB):
    formats = db.get_formats()
    media = [InputMediaPhoto(media=f.photo) for f in formats if f.photo]
    if media:
        await message.answer_media_group(media)
    await message.answer(CHOOSE_FORMAT, reply_markup=kb_formats())


async def show_workshop_list(message: Message, db: DB, fmt: str):
    workshops = db.get_workshops(only_open=True, format_filter=fmt)
    if not workshops:
        await message.answer(NO_WORKSHOPS, reply_markup=kb_formats())
        return
    await message.answer(CHOOSE_WORKSHOP, reply_markup=kb_workshops(workshops))


async def show_my_records(message: Message, user_id: int, db: DB):
    user_records = db.get_user_records(user_id)
    if not user_records:
        await message.answer(MY_RECORDS_EMPTY, reply_markup=kb_start())
        return

    titles = {w.id: w for w in db.get_workshops(include_deleted=True)}
    lines = [MY_RECORDS_TITLE, ""]
    rows = []
    for r in user_records:
        w = titles.get(r.workshop_id)
        title = w.title if w else f"Мастерская №{r.workshop_id}"
        if w and w.format == "базовая":
            title += f" ({_slot_date(w, r.slot)})"
        lines.append(my_record_line(title, r.status))
        rows.append((r.workshop_id, title, r.status))

    await message.answer("\n".join(lines), reply_markup=kb_my_records(rows))

# ==================================================
# ЗАПИСЬ И РЕЗЕРВ
# ==================================================

async def _do_register(
    message: Message,
    profile: Profile,
    workshop: Workshop,
    slot: int,
    status: str,
    db: DB,
    attendance: AttendanceClient,
):
    record = Record(
        id=0,
        telegram_id=profile.telegram_id,
        username=profile.nickname,
        workshop_id=workshop.id,
        slot=slot,
        status=status,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    try:
        db.add_record(record)
    except Exception as e:
        print(f"[records] не удалось сохранить запись: {e}")
        await message.answer(GOOGLE_RETRY)
        return

    # В файл посещаемости попадают только «основные».
    if status == "основной" and workshop.attendance_file_id:
        try:
            await attendance.add_person(
                workshop.attendance_file_id,
                workshop,
                slot,
                profile.full_name,
                profile.group,
                profile.nickname,
                profile.telegram_id,
            )
        except Exception as e:
            print(f"[attendance] не удалось добавить человека: {e}")

    date = _slot_date(workshop, slot)
    if status == "основной":
        await message.answer(SIGNED_MAIN.format(title=workshop.title, date=date))
    else:
        await message.answer(RESERVE_DONE.format(title=workshop.title, date=date))


async def _offer_promotion(bot, db: DB, workshop: Workshop, slot: int):
    """FIFO + срок 1 час: предложение живёт час, потом уходит следующему."""
    if db.count_active(workshop.id, slot) >= workshop.quota:
        return
    now = datetime.now().timestamp()
    for res in db.get_reserves(workshop.id, slot):
        key = f"offer:{res.id}"
        existing = db.kv_get(key)
        if existing:
            try:
                ts = float(existing.rsplit(":", 1)[1])
                if now - ts < PROMOTE_TTL_SEC:
                    continue  # предложение ещё действует
            except Exception:
                pass
            db.kv_set(key, "")
        db.kv_set(key, f"{workshop.id}:{slot}:{now}")
        try:
            await bot.send_message(
                res.telegram_id,
                PROMOTE_OFFER.format(
                    title=workshop.title, date=_slot_date(workshop, slot)
                ),
                reply_markup=kb_promote_offer(res.id),
            )
            return
        except Exception:
            db.kv_set(key, "")

# ==================================================
# КАЛЛБЭКИ
# ==================================================

@router.callback_query(F.data.startswith("fmt:"))
async def cb_format(callback: CallbackQuery, db: DB):
    await callback.answer()
    await show_workshop_list(callback.message, db, callback.data.split(":", 1)[1])


@router.callback_query(F.data == "back:formats")
async def cb_back_formats(callback: CallbackQuery, db: DB):
    await callback.answer()
    await show_formats(callback.message, db)


@router.callback_query(F.data.startswith("ws:"))
async def cb_workshop_card(callback: CallbackQuery, db: DB):
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    w = db.get_workshop(ws_id)
    if not w or w.deleted:
        await callback.message.answer("Мастерская не найдена.")
        return

    # Получаем все даты мастерской
    dates = db.get_workshop_dates(ws_id)

    # Формируем текст карточки
    text = workshop_card_text(w, dates=dates, db=db)

    sent = False
    if w.photo:
        try:
            await callback.message.answer_photo(
                w.photo, caption=text,
                reply_markup=kb_workshop_card(ws_id), parse_mode="HTML",
            )
            sent = True
        except Exception:
            pass
    if not sent:
        await callback.message.answer(
            text, reply_markup=kb_workshop_card(ws_id), parse_mode="HTML"
        )


@router.callback_query(F.data == "back:workshops")
async def cb_back_workshops(callback: CallbackQuery, db: DB):
    await callback.answer()
    await show_formats(callback.message, db)


@router.callback_query(F.data.startswith("signup:"))
async def cb_signup(
    callback: CallbackQuery, db: DB, attendance: AttendanceClient
):
    await callback.answer()
    ws_id = int(callback.data.split(":")[1])
    w = db.get_workshop(ws_id)
    if not w or w.deleted or not w.is_open:
        await callback.message.answer("Запись на эту мастерскую не открыта.")
        return

    tg_id = callback.from_user.id
    existing = db.get_user_record(tg_id, ws_id)
    if existing:
        await callback.message.answer(
            ALREADY_SIGNED_REAL.format(status=_status_label(existing.status))
        )
        return

    profile = db.get_profile(tg_id)
    if not profile:
        await callback.message.answer("Сначала заполни анкету.", reply_markup=kb_start())
        return

    # НОВОЕ: Если у мастерской есть даты в таблице — показываем выбор даты
    dates = db.get_workshop_dates(ws_id)
    if dates:
        await callback.message.answer(
            "Выбери дату:",
            reply_markup=kb_date_list(ws_id, dates),
        )
        return

    # Старый вариант для совместимости (если даты ещё не мигрированы)
    if w.format == "базовая" and w.date2:
        await callback.message.answer(
            ASK_SLOT, reply_markup=kb_slot_dates(ws_id, w.date1, w.date2)
        )
        return

    await _signup_slot(callback.message, profile, w, 1, db, attendance)

@router.callback_query(F.data.startswith("slot:"))
async def cb_slot(
    callback: CallbackQuery, db: DB, attendance: AttendanceClient
):
    await callback.answer()
    _, slot_raw, ws_raw = callback.data.split(":")
    slot, ws_id = int(slot_raw), int(ws_raw)
    w = db.get_workshop(ws_id)
    if not w or w.deleted:
        return

    existing = db.get_user_record(callback.from_user.id, ws_id)
    if existing:
        await callback.message.answer(
            ALREADY_SIGNED_REAL.format(status=_status_label(existing.status))
        )
        return

    profile = db.get_profile(callback.from_user.id)
    if not profile:
        return
    await _signup_slot(callback.message, profile, w, slot, db, attendance)


async def _signup_slot(
    message: Message,
    profile: Profile,
    w: Workshop,
    slot: int,
    db: DB,
    attendance: AttendanceClient,
):
    free = max(w.quota - db.count_active(w.id, slot), 0)
    if free <= 0:
        await message.answer(
            QUOTA_FULL.format(title=w.title), reply_markup=kb_reserve(w.id, slot)
        )
        return
    await _do_register(message, profile, w, slot, "основной", db, attendance)


@router.callback_query(F.data.startswith("reserve:"))
async def cb_reserve(
    callback: CallbackQuery, db: DB, attendance: AttendanceClient
):
    await callback.answer()
    _, answer, ws_raw, slot_raw = callback.data.split(":")
    w = db.get_workshop(int(ws_raw))
    if not w:
        return
    if answer == "no":
        await callback.message.answer(RESERVE_NO)
        return

    existing = db.get_user_record(callback.from_user.id, w.id)
    if existing:
        await callback.message.answer(
            ALREADY_SIGNED_REAL.format(status=_status_label(existing.status))
        )
        return

    profile = db.get_profile(callback.from_user.id)
    if not profile:
        return
    await _do_register(
        callback.message, profile, w, int(slot_raw), "резерв", db, attendance
    )

# ==================================================
# ПРЕДЛОЖЕНИЕ ПЕРЕВОДА ИЗ РЕЗЕРВА (Да / Нет, 1 час)
# ==================================================

@router.callback_query(F.data.startswith("promote:"))
@router.callback_query(F.data.startswith("promote:"))
async def cb_promote(
    callback: CallbackQuery, db: DB, attendance: AttendanceClient, export: ExportClient
):
    await callback.answer()
    _, answer, rec_raw = callback.data.split(":")
    rec_id = int(rec_raw)

    rec = db.get_record(rec_id)
    db.kv_set(f"offer:{rec.id}", "")
    if not rec:
        return
    w = db.get_workshop(rec.workshop_id)
    if not w:
        return

    if answer == "no":
        await callback.message.answer(PROMOTE_DECLINED)
        await _offer_promotion(callback.bot, db, w, rec.slot)
        return

    # answer == "yes"
    if rec.status != "резерв":
        await callback.message.answer(PROMOTE_EXPIRED)
        return
    if db.count_active(w.id, rec.slot) >= w.quota:
        await callback.message.answer(PROMOTE_EXPIRED)
        return

    db.set_record_status(rec.id, "основной")
    if w.attendance_file_id:
        p = db.get_profile(rec.telegram_id)
        if p:
            try:
                await attendance.add_person(
                    w.attendance_file_id, w, rec.slot,
                    p.full_name, p.group, p.nickname, p.telegram_id,
                )
            except Exception as e:
                print(f"[attendance] не удалось добавить поднятого: {e}")

    # НОВОЕ: Немедленно обновляем файл участников после promote
    if w.participants_file_id:
        try:
            await export.export_one(w)
        except Exception as e:
            print(f"[export] не удалось обновить файл участников после promote: {e}")

    await callback.message.answer(
        PROMOTE_YES.format(title=w.title, date=_slot_date(w, rec.slot))
    )

# ==================================================
# ОТМЕНА: освобождаем строку + предлагаем место
# ==================================================

@router.callback_query(F.data.startswith("cancel:"))
@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(
    callback: CallbackQuery, db: DB, attendance: AttendanceClient, export: ExportClient
):
    await callback.answer()
    _, action, ws_raw = callback.data.split(":")
    ws_id = int(ws_raw)
    w = db.get_workshop(ws_id)
    if not w:
        return

    if action == "ask":
        await callback.message.answer(
            ASK_CANCEL.format(title=w.title), reply_markup=kb_cancel_confirm(ws_id)
        )
        return

    if action == "no":
        await show_my_records(callback.message, callback.from_user.id, db)
        return

    # action == "yes"
    rec = db.get_user_record(callback.from_user.id, ws_id)
    if rec:
        db.set_record_status(rec.id, "отменено")
        db.kv_set(f"offer:{rec.id}", "")

        # освобождаем строку в файле посещаемости
        if w.attendance_file_id:
            try:
                await attendance.remove_person(
                    w.attendance_file_id, w, rec.slot, rec.telegram_id
                )
            except Exception as e:
                print(f"[attendance] не удалось освободить строку: {e}")

        # НОВОЕ: Немедленно обновляем файл участников после отмены
        if w.participants_file_id:
            try:
                await export.export_one(w)
            except Exception as e:
                print(f"[export] не удалось обновить файл участников после отмены: {e}")

        await callback.message.answer(CANCEL_DONE.format(title=w.title))
        await _offer_promotion(callback.bot, db, w, rec.slot)

    await show_my_records(callback.message, callback.from_user.id, db)


@router.callback_query(F.data.startswith("datepick:"))
async def cb_datepick(callback: CallbackQuery, db: DB, attendance: AttendanceClient):
    await callback.answer()
    _, date_id_raw, ws_raw = callback.data.split(":")
    date_id = int(date_id_raw)
    ws_id = int(ws_raw)

    w = db.get_workshop(ws_id)
    if not w or w.deleted:
        return

    existing = db.get_user_record(callback.from_user.id, ws_id)
    if existing:
        await callback.message.answer(
            ALREADY_SIGNED_REAL.format(status=_status_label(existing.status))
        )
        return

    profile = db.get_profile(callback.from_user.id)
    if not profile:
        await callback.message.answer("Сначала заполни анкету.", reply_markup=kb_start())
        return

    # Записываем на выбранную дату
    await _signup_by_date(callback.message, profile, w, date_id, db, attendance)


async def _signup_by_date(
        message: Message,
        profile: Profile,
        w: Workshop,
        date_id: int,
        db: DB,
        attendance: AttendanceClient,
):
    """Запись на конкретную дату по date_id."""
    free = max(w.quota - db.count_active_by_date(w.id, date_id), 0)
    if free <= 0:
        await message.answer(
            QUOTA_FULL.format(title=w.title), reply_markup=kb_reserve_by_date(w.id, date_id)
        )
        return

    date_info = db.get_workshop_date(date_id)
    date_str = date_info["date"] if date_info else ""

    await _do_register(message, profile, w, date_id, "основной", db, attendance, date_str=date_str)