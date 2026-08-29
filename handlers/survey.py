# handlers/survey.py
# FSM-анкета пользователя с подтверждением и редактированием полей.

from __future__ import annotations

import re
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.start import route_after
from keyboards import kb_confirm, kb_contact_type, kb_edit_fields
from models import Profile
from records_client import RecordsClient
from sheets_client import SheetsClient
from states import SurveyStates
from texts import (
    ASK_CONTACT_TYPE,
    ASK_EMAIL,
    ASK_FULL_NAME,
    ASK_GROUP,
    ASK_NICKNAME_TG,
    ASK_NICKNAME_VK,
    ASK_PHONE,
    PROFILE_SAVED,
    confirm_text,
)

router = Router()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EDIT_PROMPTS = {
    "full_name": ASK_FULL_NAME,
    "group": ASK_GROUP,
    "phone": ASK_PHONE,
    "email": ASK_EMAIL,
    "nickname": "Введи ник заново:",
}


def build_nickname(data: dict) -> str:
    """Собирает ник в формате хранения: tg:@nick или vk:nick."""
    kind = data.get("contact_kind", "tg")
    raw = str(data.get("nickname_raw", "")).strip()
    if kind == "tg":
        return "tg:" + (raw if raw.startswith("@") else "@" + raw)
    return "vk:" + raw


def display_data(data: dict) -> str:
    """Текст для экрана подтверждения."""
    kind = data.get("contact_kind", "tg")
    raw = str(data.get("nickname_raw", ""))
    if kind == "tg":
        nick_disp = "Telegram: " + (raw if raw.startswith("@") else "@" + raw)
    else:
        nick_disp = "VK: " + raw

    return confirm_text({
        "full_name": data.get("full_name", ""),
        "group": data.get("group", ""),
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "nickname": nick_disp,
    })


# ================== ВОПРОСЫ АНКЕТЫ ==================

@router.message(SurveyStates.full_name)
async def st_full_name(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if len(value) < 5:
        await message.answer("Слишком коротко. Введи ФИО полностью:")
        return
    await state.update_data(full_name=value)
    await state.set_state(SurveyStates.group)
    await message.answer(ASK_GROUP)


@router.message(SurveyStates.group)
async def st_group(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value:
        await message.answer(ASK_GROUP)
        return
    await state.update_data(group=value)
    await state.set_state(SurveyStates.phone)
    await message.answer(ASK_PHONE)


@router.message(SurveyStates.phone)
async def st_phone(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if len(value) < 6:
        await message.answer("Похоже, номер неполный. Введи телефон:")
        return
    await state.update_data(phone=value)
    await state.set_state(SurveyStates.email)
    await message.answer(ASK_EMAIL)


@router.message(SurveyStates.email)
async def st_email(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not EMAIL_RE.match(value):
        await message.answer(
            "Похоже, в почте ошибка. Пример: ivanov@mail.ru\nВведи ещё раз:"
        )
        return
    await state.update_data(email=value)
    await state.set_state(SurveyStates.contact_type)
    await message.answer(ASK_CONTACT_TYPE, reply_markup=kb_contact_type())


@router.callback_query(F.data.startswith("contact:"), SurveyStates.contact_type)
async def cb_contact(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":")[1]
    await callback.answer()
    await state.update_data(contact_kind=kind)
    await state.set_state(SurveyStates.nickname)
    await callback.message.answer(
        ASK_NICKNAME_TG if kind == "tg" else ASK_NICKNAME_VK
    )


@router.message(SurveyStates.nickname)
async def st_nickname(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value:
        await message.answer("Ник не может быть пустым. Введи ник:")
        return
    await state.update_data(nickname_raw=value)
    await state.set_state(SurveyStates.confirm)
    data = await state.get_data()
    await message.answer(display_data(data), reply_markup=kb_confirm())


# ================== ПОДТВЕРЖДЕНИЕ ==================

@router.callback_query(F.data == "confirm:yes", SurveyStates.confirm)
async def cb_confirm_yes(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: SheetsClient,
    records: RecordsClient,
):
    """Пользователь подтвердил анкету — сохраняем профиль."""
    await callback.answer()
    data = await state.get_data()

    profile = Profile(
        telegram_id=callback.from_user.id,
        full_name=data.get("full_name", ""),
        group=data.get("group", ""),
        phone=data.get("phone", ""),
        email=data.get("email", ""),
        nickname=build_nickname(data),
        consent_date=data.get("consent_date", ""),
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    await sheets.save_profile(profile)

    after = data.get("after", "register")
    await state.clear()
    await callback.message.answer(PROFILE_SAVED)

    await route_after(callback.message, after, sheets, records, callback.from_user.id)

@router.callback_query(F.data == "confirm:edit", SurveyStates.confirm)
async def cb_confirm_edit(callback: CallbackQuery, state: FSMContext):
    """Пользователь хочет исправить поле."""
    await callback.answer()
    await callback.message.answer(
        "Какое поле исправляем?", reply_markup=kb_edit_fields()
    )


# ================== РЕДАКТИРОВАНИЕ ==================

@router.callback_query(F.data.startswith("edit:"), SurveyStates.confirm)
async def cb_edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    await callback.answer()

    if field == "back":
        data = await state.get_data()
        await callback.message.answer(
            display_data(data), reply_markup=kb_confirm()
        )
        return

    await state.update_data(edit_field=field)
    await state.set_state(SurveyStates.edit_value)
    await callback.message.answer(EDIT_PROMPTS[field])


@router.message(SurveyStates.edit_value)
async def st_edit_value(message: Message, state: FSMContext):
    """Принимает новое значение поля и возвращает к подтверждению."""
    value = (message.text or "").strip()
    data = await state.get_data()
    field = data.get("edit_field", "full_name")

    if field == "email" and not EMAIL_RE.match(value):
        await message.answer("Похоже, в почте ошибка. Введи ещё раз:")
        return
    if field == "nickname":
        if not value:
            await message.answer("Ник не может быть пустым. Введи ник:")
            return
        await state.update_data(nickname_raw=value)
    else:
        if not value:
            await message.answer("Значение не может быть пустым. Введи ещё раз:")
            return
        await state.update_data(**{field: value})

    await state.set_state(SurveyStates.confirm)
    data = await state.get_data()
    await message.answer(display_data(data), reply_markup=kb_confirm())
