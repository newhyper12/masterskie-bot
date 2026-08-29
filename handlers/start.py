# handlers/start.py
# /start, главное меню, согласие на обработку персональных данных.

from __future__ import annotations

import os

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards import kb_consent, kb_start
from records_client import RecordsClient
from sheets_client import SheetsClient
from states import SurveyStates
from texts import ASK_FULL_NAME, CONSENT_TEXT, START_TEXT

router = Router()


async def route_after(
    obj, after: str, sheets: SheetsClient, records: RecordsClient, user_id: int
):
    """
    Куда вести пользователя после того, как профиль готов.
    """
    if after == "my":
        from handlers.workshop import show_my_records
        await show_my_records(obj, user_id, sheets, records)
    else:
        from handlers.workshop import show_formats
        await show_formats(obj, sheets)


async def require_profile(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: SheetsClient,
    records: RecordsClient,
    after: str,
):
    """
    Если профиль уже заполнен — сразу ведём дальше.
    Если нет — показываем согласие 152-ФЗ и начинаем анкету.
    """
    await callback.answer()

    profile = await sheets.get_profile(callback.from_user.id)
    if profile:
        await route_after(
            callback.message, after, sheets, records, callback.from_user.id
        )
        return

    await state.set_state(SurveyStates.consent)
    await state.update_data(after=after)
    await callback.message.answer(CONSENT_TEXT, reply_markup=kb_consent())


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Стартовое сообщение с информацией о проекте."""
    # Если в .env есть START_PHOTO_ID — отправим с фото.
    # Это должен быть file_id из Telegram (см. инструкцию ниже).
    photo_id = os.getenv("START_PHOTO_ID", "").strip()
    if photo_id:
        try:
            await message.answer_photo(
                photo_id,
                caption=START_TEXT,
                reply_markup=kb_start(),
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    await message.answer(START_TEXT, reply_markup=kb_start(), parse_mode="HTML")


@router.callback_query(F.data == "menu:register")
async def cb_register(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: SheetsClient,
    records: RecordsClient,
):
    """Кнопка «📝 Регистрация на МК»."""
    await require_profile(callback, state, sheets, records, after="register")


@router.callback_query(F.data == "menu:my")
async def cb_my(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: SheetsClient,
    records: RecordsClient,
):
    """Кнопка «📋 Мои записи»."""
    await require_profile(callback, state, sheets, records, after="my")


@router.callback_query(F.data == "consent:yes", SurveyStates.consent)
async def cb_consent(callback: CallbackQuery, state: FSMContext):
    """
    Единственная кнопка согласия.
    Без неё анкета просто не начнётся.
    """
    await callback.answer()

    from datetime import datetime
    await state.update_data(
        consent_date=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    await state.set_state(SurveyStates.full_name)
    await callback.message.answer(ASK_FULL_NAME)


@router.callback_query(F.data == "back:menu")
async def cb_back_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню."""
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        START_TEXT, reply_markup=kb_start(), parse_mode="HTML"
    )
