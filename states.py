# states.py
# Все FSM-состояния бота.

from aiogram.fsm.state import State, StatesGroup


class SurveyStates(StatesGroup):
    consent = State()
    full_name = State()
    group = State()
    phone = State()
    email = State()
    contact_type = State()
    nickname = State()
    confirm = State()
    edit_value = State()
    birth_date = State()       # НОВОЕ: ввод даты рождения


class AdminWorkshopStates(StatesGroup):
    title = State()
    format = State()
    description = State()
    date1 = State()
    date2 = State()
    location = State()
    lessons = State()
    days = State()
    quota = State()
    photo = State()
    open_at = State()
    close_at = State()


class AdminScheduleStates(StatesGroup):
    open_at = State()
    close_at = State()


class AdminEditStates(StatesGroup):
    value = State()
    photo = State()


class AdminServiceStates(StatesGroup):
    format_photo = State()
    start_photo = State()
    start_text = State()


class AdminReminderStates(StatesGroup):
    audience = State()
    text = State()


class AdminBroadcastStates(StatesGroup):   # НОВОЕ: рассылка всем
    text = State()