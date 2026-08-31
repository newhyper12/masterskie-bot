# handlers/survey.py
# Анкета пользователя при первом запуске (согласие 152-ФЗ + данные).

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
    ASK_EMAIL,
    ASK_FULL_NAME,
    ASK_GROUP,
    ASK_NICKNAME,
    ASK_PHONE,
    profile_confirm_text,
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


@router.callback_query(F.data == "consent:yes", SurveyStates.consent)
async def cb_consent(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(consent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    await state.set_state(SurveyStates.full_name)
    await callback.message.answer(ASK_FULL_NAME)


@router.message(SurveyStates.full_name)
async def st_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=(message.text or "").strip())
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
    await message.answer(ASK_NICKNAME.replace("Контакт", "Куда писать") if False else "Куда писать: Telegram или VK?", reply_markup=kb_contact_type())


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
    )