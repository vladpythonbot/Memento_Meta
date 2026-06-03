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
BTN_SAVED = "🗂 Сохранённое"


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_APP), KeyboardButton(text=BTN_CAPTURE)],
    ],
    resize_keyboard=True,
)


def app_links_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup | None:
    if not webapp_url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть панель", web_app=WebAppInfo(url=f"{webapp_url}/app?v=4"))],
        ]
    )


def capture_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Заметка", callback_data="capture_note"),
                InlineKeyboardButton(text="Задача", callback_data="capture_task"),
            ],
        ]
    )


def task_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data=f"task_done:{task_id}")],
            [InlineKeyboardButton(text="Матрица", callback_data=f"matrix_pick:{task_id}")],
        ]
    )


def today_tasks_keyboard(tasks) -> InlineKeyboardMarkup | None:
    if not tasks:
        return None

    rows = []
    for task in tasks[:8]:
        title = task.title if len(task.title) <= 28 else task.title[:25] + "..."
        rows.append([
            InlineKeyboardButton(text=f"Готово · {title}", callback_data=f"task_done:{task.id}"),
            InlineKeyboardButton(text="Матрица", callback_data=f"matrix_pick:{task.id}"),
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def matrix_choice_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Важно + срочно", callback_data=f"matrix_set:{task_id}:do")],
            [InlineKeyboardButton(text="Важно, не срочно", callback_data=f"matrix_set:{task_id}:plan")],
            [InlineKeyboardButton(text="Срочно, не важно", callback_data=f"matrix_set:{task_id}:delegate")],
            [InlineKeyboardButton(text="Не важно и не срочно", callback_data=f"matrix_set:{task_id}:drop")],
        ]
    )


def matrix_tasks_keyboard(tasks, webapp_url: str | None = None) -> InlineKeyboardMarkup | None:
    rows = []

    if webapp_url:
        rows.append([InlineKeyboardButton(text="Открыть матрицу", web_app=WebAppInfo(url=f"{webapp_url}/matrix?v=3.7"))])

    if not tasks:
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

    for task in tasks[:10]:
        title = task.title if len(task.title) <= 28 else task.title[:25] + "..."
        prefix = "Разнести" if task.important is None or task.urgent is None else "Изменить"
        rows.append([InlineKeyboardButton(text=f"{prefix} · {title}", callback_data=f"matrix_pick:{task.id}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def saved_notes_keyboard(notes) -> InlineKeyboardMarkup | None:
    if not notes:
        return None

    rows = []
    for index, note in enumerate(notes[:10], start=1):
        rows.append([InlineKeyboardButton(text=f"Удалить #{index}", callback_data=f"note_delete:{note.id}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def focus_methods_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []

    if webapp_url:
        rows.append([InlineKeyboardButton(text="Открыть фокус", web_app=WebAppInfo(url=f"{webapp_url}/focus?v=3.7"))])

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
