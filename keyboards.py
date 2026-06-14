from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)


BTN_CAPTURE = "📝 Записать"
BTN_APP = "🧭 Панель"
BTN_TODAY = "📅 Сегодня"
BTN_FOCUS = "🎯 Фокус"
BTN_MATRIX = "🧭 Матрица"
BTN_SUMMARY = "📊 Итог"
BTN_REVIEW = "🧾 Обзор"


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_APP)],
    ],
    resize_keyboard=True,
)


def app_links_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup | None:
    if not webapp_url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть панель", web_app=WebAppInfo(url=f"{webapp_url}/app?v=5"))],
        ]
    )


def matrix_choice_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Важно + срочно", callback_data=f"matrix_set:{task_id}:do")],
            [InlineKeyboardButton(text="Важно, не срочно", callback_data=f"matrix_set:{task_id}:plan")],
            [InlineKeyboardButton(text="Срочно, не важно", callback_data=f"matrix_set:{task_id}:delegate")],
            [InlineKeyboardButton(text="Не важно и не срочно", callback_data=f"matrix_set:{task_id}:drop")],
        ]
    )


def focus_methods_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []

    if webapp_url:
        rows.append([InlineKeyboardButton(text="Открыть фокус", web_app=WebAppInfo(url=f"{webapp_url}/focus?v=5"))])

    rows.extend([
            [InlineKeyboardButton(text="Pomodoro · 25 мин", callback_data="focus:Pomodoro:25")],
            [InlineKeyboardButton(text="Short Focus · 15 мин", callback_data="focus:Short Focus:15")],
            [InlineKeyboardButton(text="Deep Work · 90 мин", callback_data="focus:Deep Work:90")],
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def active_focus_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Завершить", callback_data=f"focus_finish:{session_id}"),
                InlineKeyboardButton(text="Отменить", callback_data=f"focus_cancel:{session_id}"),
            ],
        ]
    )

