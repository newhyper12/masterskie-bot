# handlers/start.py
# /start одним сообщением + постоянная нижняя кнопка «🏠 Меню» для всех устройств.
# Фото и текст могут работать вместе.

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, MessageEntity

from db import DB
from keyboards import kb_consent, kb_main_reply, kb_start
from states import SurveyStates
from texts import CONSENT_TEXT, START_TEXT

router = Router()


async def _send_start(message: Message, db: DB):
    """Фото + текст вместе, если заданы оба."""
    photo = db.kv_get("START_PHOTO_ID")
    stored = db.kv_get("START_MESSAGE")

    ents = None
    text = START_TEXT
    if stored:
        try:
            data = json.loads(stored)
            ents = [
                MessageEntity(
                    type=e["type"], offset=e["offset"], length=e["length"],
                    custom_emoji_id=e.get("custom_emoji_id"),
                )
                for e in data.get("entities", [])
                if e["type"] in ("custom_emoji", "bold", "italic", "underline")
            ]
            text = data["text"]
        except Exception:
            ents = None

    if photo:
        try:
            await message.answer_photo(
                photo, caption=text, entities=ents, reply_markup=kb_main_reply()
            )
            return
        except Exception:
            pass

    await message.answer(text, entities=ents, reply_markup=kb_main_reply())


async def _send_menu(obj):
    await obj.answer("Меню 👇", reply_markup=kb_start())


@router.message(Command("start"))
async def cmd_start(message: Message, db: DB):
    await _send_start(message, db)


@router.message(F.text == "🏠 Меню")
async def msg_menu(message: Message, db: DB):
    await _send_menu(message)


@router.message(F.text == "📝 Регистрация на МК")
async def msg_register(message: Message, state: FSMContext, db: DB):
    await require_profile_msg(message, "register", state, db)


@router.message(F.text == "📋 Мои записи")
async def msg_my(message: Message, state: FSMContext, db: DB):
    await require_profile_msg(message, "my", state, db)


async def require_profile_msg(message: Message, after: str, state: FSMContext, db: DB):
    profile = db.get_profile(message.from_user.id)
    if profile:
        await route_after(message, after, db, message.from_user.id)
        return
    await state.update_data(after=after)
    await state.set_state(SurveyStates.consent)
    await message.answer(CONSENT_TEXT, reply_markup=kb_consent())


@router.callback_query(F.data == "menu:register")
async def cb_register(callback: CallbackQuery, state: FSMContext, db: DB):
    await require_profile(callback, "register", state, db)


@router.callback_query(F.data == "menu:my")
async def cb_my(callback: CallbackQuery, state: FSMContext, db: DB):
    await require_profile(callback, "my", state, db)


@router.callback_query(F.data == "back:menu")
async def cb_back_menu(callback: CallbackQuery, db: DB):
    await callback.answer()
    await _send_menu(callback.message)


async def require_profile(callback: CallbackQuery, after: str, state: FSMContext, db: DB):
    await callback.answer()
    profile = db.get_profile(callback.from_user.id)
    if profile:
        await route_after(callback.message, after, db, callback.from_user.id)
        return
    await state.update_data(after=after)
    await state.set_state(SurveyStates.consent)
    await callback.message.answer(CONSENT_TEXT, reply_markup=kb_consent())


async def route_after(obj, after: str, db: DB, user_id: int):
    if after == "my":
        from handlers.workshop import show_my_records
        await show_my_records(obj, user_id, db)
    else:
        from handlers.workshop import show_formats
        await show_formats(obj, db)