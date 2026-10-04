# handlers/survey.py
# Анкета пользователя при первом запуске (согласие 152-ФЗ + данные)
# + сбор даты рождения по кнопке из рассылки.

from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import DB
from keyboards import (
    kb_confirm,
    kb_contact_type,
    kb_edit_fields,
)
from models import Profile
from states import SurveyStates
from texts import (
    ASK_BIRTH_DATE,
    ASK_EMAIL,
    ASK_FULL_NAME,
    ASK_GROUP,
    ASK_NICKNAME,
    ASK_PHONE,
    BIRTH_BAD,
    BIRTH_SAVED,
    EDIT_ASK_VALUE,
    profile_confirm_text,
    ASK_UPDATE_FULLNAME,
    FULLNAME_BAD,
    FULLNAME_SAVED,
)
from handlers.start import route_after

router = Router()

FIELD_LABELS = {
    "full_name": "ФИО",
    "group": "группа",
    "phone": "телефон",
    "email": "почта",
    "nickname": "контакт",
}


def _parse_birth_date(value: str) -> str | None:
    """Принимает ДД.ММ.ГГГГ (или ДД.ММ.ГГ), возвращает ДД.ММ.ГГГГ или None."""
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    return None


@router.callback_query(F.data == "consent:yes", SurveyStates.consent)
async def cb_consent(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(consent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    await state.set_state(SurveyStates.full_name)
    await callback.message.answer(ASK_FULL_NAME)


@router.message(SurveyStates.full_name)
async def st_full_name(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if len(value.split()) < 3:
        await message.answer("Укажи полностью: Фамилия Имя Отчество (три слова).")
        return
    await state.update_data(full_name=value)
    await state.set_state(SurveyStates.group)
    await message.answer(ASK_GROUP)


@router.message(SurveyStates.group)
async def st_group(message: Message, state: FSMContext):
    await state.update_data(group=(message.text or "").strip())
    await state.set_state(SurveyStates.phone)
    await message.answer(ASK_PHONE)


@router.message(SurveyStates.phone)
async def st_phone(message: Message, state: FSMContext):
    await state.update_data(phone=(message.text or "").strip())
    await state.set_state(SurveyStates.email)
    await message.answer(ASK_EMAIL)


@router.message(SurveyStates.email)
async def st_email(message: Message, state: FSMContext):
    await state.update_data(email=(message.text or "").strip())
    await state.set_state(SurveyStates.contact_type)
    await message.answer("Куда писать: Telegram или VK?", reply_markup=kb_contact_type())


@router.callback_query(F.data.startswith("contact:"), SurveyStates.contact_type)
async def cb_contact(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(contact_kind=callback.data.split(":")[1])
    await state.set_state(SurveyStates.nickname)
    await callback.message.answer(ASK_NICKNAME)


@router.message(SurveyStates.nickname)
async def st_nickname(message: Message, state: FSMContext):
    await state.update_data(nickname=(message.text or "").strip().lstrip("@"))
    await state.set_state(SurveyStates.confirm)
    data = await state.get_data()
    await message.answer(
        profile_confirm_text(_build_profile(message.from_user.id, data)),
        reply_markup=kb_confirm(),
    )


@router.callback_query(F.data == "confirm:edit", SurveyStates.confirm)
async def cb_confirm_edit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Что исправить?", reply_markup=kb_edit_fields())


@router.callback_query(F.data.startswith("edit:"), SurveyStates.confirm)
async def cb_edit_field(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    field = callback.data.split(":")[1]
    if field == "back":
        data = await state.get_data()
        await callback.message.answer(
            profile_confirm_text(_build_profile(callback.from_user.id, data)),
            reply_markup=kb_confirm(),
        )
        return
    await state.update_data(edit_field=field)
    await state.set_state(SurveyStates.edit_value)
    await callback.message.answer(EDIT_ASK_VALUE.format(field=FIELD_LABELS[field]))


@router.message(SurveyStates.edit_value)
async def st_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field", "full_name")
    await state.update_data(**{field: (message.text or "").strip().lstrip("@")})
    await state.set_state(SurveyStates.confirm)
    data = await state.get_data()
    await message.answer(
        profile_confirm_text(_build_profile(message.from_user.id, data)),
        reply_markup=kb_confirm(),
    )


@router.callback_query(F.data == "confirm:yes", SurveyStates.confirm)
async def cb_confirm_yes(callback: CallbackQuery, state: FSMContext, db: DB):
    await callback.answer()
    data = await state.get_data()
    profile = _build_profile(callback.from_user.id, data)
    db.save_profile(profile)
    after = data.get("after", "register")
    await state.clear()
    await route_after(callback.message, after, db, callback.from_user.id)


# ==================================================
# НОВОЕ: СБОР ДАТЫ РОЖДЕНИЯ (кнопка в рассылке)
# ==================================================

@router.callback_query(F.data == "birth:set")
async def cb_birth_set(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SurveyStates.birth_date)
    await callback.message.answer(ASK_BIRTH_DATE)


@router.message(SurveyStates.birth_date)
async def st_birth_date(message: Message, state: FSMContext, db: DB):
    parsed = _parse_birth_date(message.text or "")
    if parsed is None:
        await message.answer(BIRTH_BAD)
        return

    profile = db.get_profile(message.from_user.id)
    if not profile:
        await state.clear()
        await message.answer("Сначала заполни анкету: /start → Регистрация.")
        return

    profile.birth_date = parsed
    profile.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.save_profile(profile)
    await state.clear()
    await message.answer(BIRTH_SAVED.format(date=parsed))


def _build_profile(telegram_id: int, data: dict) -> Profile:
    kind = data.get("contact_kind", "tg")
    nick = data.get("nickname", "")
    return Profile(
        telegram_id=telegram_id,
        full_name=data.get("full_name", ""),
        group=data.get("group", ""),
        phone=data.get("phone", ""),
        email=data.get("email", ""),
        nickname=("@" + nick) if kind == "tg" else f"vk: {nick}",
        consent_date=data.get("consent_at", ""),
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        birth_date=data.get("birth_date", ""),
    )

@router.message(SurveyStates.fullname_update)
async def st_fullname_update(message: Message, state: FSMContext, db: DB):
    value = (message.text or "").strip()
    if len(value.split()) < 3:
        await message.answer(FULLNAME_BAD)
        return

    profile = db.get_profile(message.from_user.id)
    if not profile:
        await state.clear()
        await message.answer("Сначала заполни анкету: /start → Регистрация.")
        return

    profile.full_name = value
    profile.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.save_profile(profile)
    await state.clear()
    await message.answer(FULLNAME_SAVED.format(fullname=value))