# handlers/start.py
# /start: приветственное сообщение с inline-кнопками («Регистрация», «Мои записи»)
# + нижняя кнопка «🏠 Меню» под строкой ввода. Отдельных сообщений «Меню» нет.

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


async def _send_start(obj: Message, db: DB):
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

    # 1) Приветствие с inline-кнопками «Регистрация» и «Мои записи».
    sent = None
    if photo:
        try:
            sent = await obj.answer_photo(
                photo, caption=text, caption_entities=ents,
                reply_markup=kb_start(),
            )
        except Exception:
            sent = None
    if sent is None:
        sent = await obj.answer(text, entities=ents, reply_markup=kb_start())

    # 2) Нижняя клавиатура «🏠 Меню»: ставим её служебным сообщением
    #    и сразу удаляем его. Сообщений «Меню» пользователь не видит.
    try:
        anchor = await obj.answer("\u200b", reply_markup=kb_main_reply())
        await anchor.delete()
    except Exception as e:
        print(f"[start] не удалось поставить нижнюю клавиатуру: {e}")


@router.message(Command("start"))
async def cmd_start(message: Message, db: DB):
    await _send_start(message, db)


# ==================================================
# НИЖНЯЯ КЛАВИАТУРА
# ==================================================

@router.message(F.text == "🏠 Меню")
async def msg_menu(message: Message, db: DB):
    """Нижняя кнопка: показываем приветствие с кнопками заново."""
    await _send_start(message, db)


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


# ==================================================
# INLINE-ВХОДЫ
# ==================================================

@router.callback_query(F.data == "menu:register")
async def cb_register(callback: CallbackQuery, state: FSMContext, db: DB):
    await require_profile(callback, "register", state, db)


@router.callback_query(F.data == "menu:my")
async def cb_my(callback: CallbackQuery, state: FSMContext, db: DB):
    await require_profile(callback, "my", state, db)


@router.callback_query(F.data == "back:menu")
async def cb_back_menu(callback: CallbackQuery, db: DB):
    await callback.answer()
    await _send_start(callback.message, db)


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