import asyncio
import datetime as dt
from html import escape
from types import SimpleNamespace

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot import bot
from config import WEBAPP_URL
from db import (
    add_task,
    cancel_focus_session,
    complete_task,
    ensure_user,
    finish_focus_session,
    get_daily_summary,
    get_active_focus_session,
    get_matrix_tasks,
    get_next_action_task,
    get_open_tasks,
    get_period_summary,
    start_focus_session,
    update_task_matrix,
)
from keyboards import (
    BTN_APP,
    BTN_CAPTURE,
    BTN_FOCUS,
    BTN_MATRIX,
    BTN_REVIEW,
    BTN_SUMMARY,
    BTN_TODAY,
    active_focus_keyboard,
    app_links_keyboard,
    focus_methods_keyboard,
    main_keyboard,
    matrix_choice_keyboard,
)


router = Router()


FOCUS_METHOD_HINTS = {
    "Pomodoro": "Для обычной задачи, когда нужно мягко войти в работу.",
    "Short Focus": "Для короткого рывка, если мало сил или много сопротивления.",
    "Deep Work": "Для большой задачи, где нужна тишина и длинная концентрация.",
}

FOCUS_FRAMES = ["·", "∙", "●", "∙"]

DAY_BAR = "▁▂▃▄▅▆▇█"


def is_command_text(text: str) -> bool:
    return text.strip().startswith("/")


def split_capture_items(text: str) -> list[str]:
    items = [line.strip(" -•\t") for line in text.splitlines()]
    return [item for item in items if len(item) >= 2]


async def save_quick_tasks(message: types.Message, state: FSMContext, text: str):
    if len(text) < 2:
        await message.answer("Слишком коротко. Напиши чуть подробнее.")
        return

    await ensure_user(message.from_user.id, message.from_user.first_name)
    await state.clear()

    items = split_capture_items(text) or [text]
    task_ids = [await add_task(message.from_user.id, item[:500]) for item in items]

    if len(task_ids) == 1:
        await message.answer(
            f"Добавил во входящие:\n\n<b>{escape(items[0])}</b>",
            parse_mode="HTML",
        )
        return

    await message.answer(
        f"Добавил во входящие: <b>{len(task_ids)}</b>\n\nРазберёшь их в панели.",
        parse_mode="HTML",
        reply_markup=app_links_keyboard(WEBAPP_URL or None),
    )


class CaptureState(StatesGroup):
    wait_text = State()


@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id, message.from_user.first_name)

    name = message.from_user.first_name or "друг"
    await message.answer(
        f"Привет, {escape(name)}.\n\n"
        "Я Noto Memento.\n\n"
        "Пиши сюда мысль, задачу или список — я сложу во входящие. Разбор, матрица и фокус живут в панели.",
        reply_markup=main_keyboard,
    )


@router.message(F.text == BTN_APP)
async def app_home(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    await message.answer(
        "🧭 <b>Панель</b>\n\n"
        "Сегодня, матрица и фокус в одном месте.",
        parse_mode="HTML",
        reply_markup=app_links_keyboard(WEBAPP_URL or None),
    )


@router.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "Коротко:\n\n"
        "Просто отправь текст — я положу его во входящие.\n"
        "Несколько строк — несколько пунктов.\n"
        "🧭 Панель — входящие, матрица и фокус."
    )


@router.message(Command("settings"))
async def settings(message: types.Message):
    await message.answer(
        "Настроек пока немного.\n\n"
        "Язык: русский\n"
        "Фокус-методы: Pomodoro, Short Focus, Deep Work\n"
        "Методы планирования: матрица Эйзенхауэра\n"
        "Свободный текст: сразу попадает во входящие"
    )


@router.message(Command("task"))
async def quick_task(message: types.Message):
    text = message.text.partition(" ")[2].strip() if message.text else ""
    if not text:
        await message.answer("Напиши так: <code>/task разобрать почту</code>", parse_mode="HTML")
        return

    await ensure_user(message.from_user.id, message.from_user.first_name)
    await add_task(message.from_user.id, text)
    await message.answer(
        f"Добавил во входящие:\n\n<b>{escape(text)}</b>",
        parse_mode="HTML",
    )


@router.message(Command("matrix", "eisenhower"))
@router.message(F.text == BTN_MATRIX)
async def matrix(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    text, reply_markup = await build_matrix_view(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.message(F.text == BTN_CAPTURE)
async def capture_start(message: types.Message, state: FSMContext):
    await state.set_state(CaptureState.wait_text)
    await message.answer(
        "Напиши мысль или задачу одним сообщением.\n\n"
        "Если пунктов несколько — отправь списком, каждый с новой строки."
    )


async def handle_navigation_during_capture(message: types.Message, state: FSMContext, text: str) -> bool:
    if text == BTN_APP:
        await state.clear()
        await app_home(message)
        return True
    if text == BTN_TODAY:
        await state.clear()
        await today(message)
        return True
    if text == BTN_FOCUS:
        await state.clear()
        await focus(message)
        return True
    if text == BTN_MATRIX:
        await state.clear()
        await matrix(message)
        return True
    if text == BTN_SUMMARY:
        await state.clear()
        await summary(message)
        return True
    if text == BTN_REVIEW:
        await state.clear()
        await review(message)
        return True
    if text == BTN_CAPTURE:
        await capture_start(message, state)
        return True

    if not is_command_text(text):
        return False

    command = text.split(maxsplit=1)[0].lower()
    await state.clear()

    if command == "/start":
        await start(message, state)
    elif command == "/help":
        await help_command(message)
    elif command == "/settings":
        await settings(message)
    elif command == "/task":
        await quick_task(message)
    elif command in {"/matrix", "/eisenhower"}:
        await matrix(message)
    elif command == "/focus":
        await focus(message)
    elif command == "/today":
        await today(message)
    elif command == "/summary":
        await summary(message)
    elif command == "/review":
        await review(message)
    else:
        await message.answer("Не знаю такую команду. Нажми /help, чтобы посмотреть доступные.")

    return True


@router.message(CaptureState.wait_text)
async def capture_text(message: types.Message, state: FSMContext):
    text = (message.text or message.caption or "").strip()
    if await handle_navigation_during_capture(message, state, text):
        return

    await save_quick_tasks(message, state, text)


@router.message(F.text == BTN_TODAY)
@router.message(Command("today"))
async def today(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    text, reply_markup = await build_today_view(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


async def build_today_view(user_id: int):
    tasks = await get_open_tasks(user_id, limit=7)
    summary = await get_daily_summary(user_id)
    next_task = await get_next_action_task(user_id)
    active_focus = await get_active_focus_session(user_id)

    lines = ["📅 <b>Сегодня</b>", ""]

    if active_focus:
        lines.append(f"🎯 Идёт фокус: <b>{escape(active_focus.method)}</b>")
        lines.append("")

    if next_task:
        lines.append("<b>Следующий шаг</b>")
        lines.append(f"{matrix_badge(next_task)} {escape(next_task.title)}")
        lines.append("")

    if tasks:
        lines.append("<b>Задачи</b>")
        for task in tasks:
            lines.append(f"• {escape(task.title)}")
    else:
        lines.append("Задач на сегодня пока нет.")

    lines.append("")
    lines.append(
        f"Итог: {summary['done_tasks']} готово · "
        f"{summary['focus_minutes']} мин фокуса"
    )

    return "\n".join(lines), app_links_keyboard(WEBAPP_URL or None)


def matrix_badge(task) -> str:
    if task.important is True and task.urgent is True:
        return "🔥"
    if task.important is True and task.urgent is False:
        return "📌"
    if task.important is False and task.urgent is True:
        return "⚡"
    if task.important is False and task.urgent is False:
        return "🧹"
    return "▫️"


async def build_matrix_view(user_id: int):
    tasks = await get_matrix_tasks(user_id)

    if not tasks:
        return "\n".join([
            "🧭 <b>Матрица Эйзенхауэра</b>",
            "",
            "Открытых задач пока нет. Просто напиши задачу в чат.",
        ]), app_links_keyboard(WEBAPP_URL or None)

    counts = count_matrix_tasks(tasks)
    lines = [
        "🧭 <b>Матрица Эйзенхауэра</b>",
        "",
        "Открой Web App, чтобы писать задачи и раскладывать их по квадрантам на одном экране.",
        "",
        f"🔥 Сделать сейчас: <b>{counts['do']}</b>",
        f"📌 Запланировать: <b>{counts['plan']}</b>",
        f"⚡ Делегировать: <b>{counts['delegate']}</b>",
        f"🧹 Убрать: <b>{counts['drop']}</b>",
        f"▫️ Без квадранта: <b>{counts['inbox']}</b>",
    ]

    return "\n".join(lines), app_links_keyboard(WEBAPP_URL or None)


def count_matrix_tasks(tasks) -> dict[str, int]:
    counts = {"do": 0, "plan": 0, "delegate": 0, "drop": 0, "inbox": 0}
    for task in tasks:
        if task.important is True and task.urgent is True:
            counts["do"] += 1
        elif task.important is True and task.urgent is False:
            counts["plan"] += 1
        elif task.important is False and task.urgent is True:
            counts["delegate"] += 1
        elif task.important is False and task.urgent is False:
            counts["drop"] += 1
        else:
            counts["inbox"] += 1
    return counts


@router.callback_query(F.data.startswith("task_done:"))
async def task_done(callback: types.CallbackQuery):
    task_id = int(callback.data.split(":", 1)[1])
    done = await complete_task(callback.from_user.id, task_id)

    if not done:
        await callback.answer("Задача уже закрыта или не найдена.", show_alert=True)
        return

    text, reply_markup = await build_today_view(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await callback.answer()


@router.callback_query(F.data.startswith("matrix_pick:"))
async def matrix_pick(callback: types.CallbackQuery):
    task_id = int(callback.data.split(":", 1)[1])
    await callback.message.edit_text(
        "Выбери квадрант для задачи.",
        reply_markup=matrix_choice_keyboard(task_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("matrix_set:"))
async def matrix_set(callback: types.CallbackQuery):
    _, raw_task_id, quadrant = callback.data.split(":", 2)
    task_id = int(raw_task_id)

    mapping = {
        "do": (True, True),
        "plan": (True, False),
        "delegate": (False, True),
        "drop": (False, False),
    }
    important, urgent = mapping[quadrant]
    updated = await update_task_matrix(callback.from_user.id, task_id, important, urgent)

    if not updated:
        await callback.answer("Задача не найдена или уже закрыта.", show_alert=True)
        return

    text, reply_markup = await build_matrix_view(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await callback.answer()


@router.message(F.text == BTN_FOCUS)
@router.message(Command("focus"))
async def focus(message: types.Message):
    active = await get_active_focus_session(message.from_user.id)
    if active:
        await message.answer(
            build_focus_status_text(active),
            parse_mode="HTML",
            reply_markup=active_focus_keyboard(active.id),
        )
        return

    await message.answer(
        "🎯 <b>Фокус</b>\n\n"
        "Выбери режим под текущее состояние:\n\n"
        "<b>Pomodoro</b> — обычная рабочая задача.\n"
        "<b>Short Focus</b> — короткий рывок без давления.\n"
        "<b>Deep Work</b> — глубокая работа без переключений.",
        parse_mode="HTML",
        reply_markup=focus_methods_keyboard(WEBAPP_URL or None),
    )


@router.callback_query(F.data.startswith("focus:"))
async def focus_start(callback: types.CallbackQuery):
    _, method, raw_minutes = callback.data.split(":", 2)
    minutes = int(raw_minutes)
    active = await get_active_focus_session(callback.from_user.id)

    if active:
        await callback.message.edit_text(
            build_focus_status_text(active),
            parse_mode="HTML",
            reply_markup=active_focus_keyboard(active.id),
        )
        await callback.answer("У тебя уже идёт фокус-сессия.", show_alert=True)
        return

    session_id = await start_focus_session(callback.from_user.id, method, minutes)

    await callback.message.edit_text(
        build_focus_status_text(
            SimpleNamespace(
                id=session_id,
                method=method,
                duration_minutes=minutes,
                started_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            ),
            frame=0,
        )
        + "\n\n"
        f"{escape(FOCUS_METHOD_HINTS.get(method, 'Работай только над одним делом.'))}\n\n"
        "Убери лишнее и работай только над одним делом.",
        parse_mode="HTML",
        reply_markup=active_focus_keyboard(session_id),
    )
    await callback.answer()
    await pin_focus_message(callback.message.chat.id, callback.message.message_id)

    asyncio.create_task(
        finish_focus_later(
            callback.from_user.id,
            session_id,
            method,
            minutes,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    )
    asyncio.create_task(
        animate_focus_session(
            callback.from_user.id,
            callback.message.chat.id,
            callback.message.message_id,
            session_id,
        )
    )


def build_focus_status_text(session, frame: int = 0) -> str:
    started = dt.datetime.fromisoformat(session.started_at)
    now = dt.datetime.now(dt.UTC)
    elapsed_seconds = max(0, int((now - started).total_seconds()))
    total_seconds = max(1, session.duration_minutes * 60)
    elapsed = elapsed_seconds // 60
    left = max(0, (total_seconds - elapsed_seconds + 59) // 60)
    progress = min(1, elapsed_seconds / total_seconds)
    filled = min(10, int(progress * 10))
    bar = "■" * filled + "□" * (10 - filled)
    pulse = FOCUS_FRAMES[frame % len(FOCUS_FRAMES)]

    return (
        f"🎯 <b>{escape(session.method)}</b> {pulse}\n\n"
        f"<code>{bar}</code> <b>{round(progress * 100)}%</b>\n"
        f"Длительность: <b>{session.duration_minutes} мин</b>\n"
        f"Прошло: <b>{elapsed} мин</b>\n"
        f"Осталось: <b>{left} мин</b>\n\n"
        "Держи один фокус. Всё лишнее потом."
    )


async def build_focus_report_text(user_id: int, method: str, minutes: int) -> str:
    data = await get_daily_summary(user_id)
    return (
        "✅ <b>Концентрация завершена</b>\n\n"
        f"Режим: <b>{escape(method)}</b>\n"
        f"Длительность: <b>{minutes} мин</b>\n\n"
        "📊 <b>Итог дня</b>\n"
        f"Готовые задачи: <b>{data['done_tasks']}</b>\n"
        f"Открытые задачи: <b>{data['open_tasks']}</b>\n"
        f"Фокус: <b>{data['focus_minutes']} мин</b>\n\n"
        "Сделай короткую паузу и выбери следующий шаг."
    )


async def pin_focus_message(chat_id: int, message_id: int) -> None:
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
    except TelegramBadRequest:
        pass


async def animate_focus_session(user_id: int, chat_id: int, message_id: int, session_id: int):
    frame = 1

    while True:
        await asyncio.sleep(15)
        active = await get_active_focus_session(user_id)

        if not active or active.id != session_id:
            return

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=build_focus_status_text(active, frame=frame),
                parse_mode="HTML",
                reply_markup=active_focus_keyboard(session_id),
            )
        except TelegramBadRequest:
            pass

        frame += 1


@router.callback_query(F.data.startswith("focus_finish:"))
async def focus_finish(callback: types.CallbackQuery):
    session_id = int(callback.data.split(":", 1)[1])
    active = await get_active_focus_session(callback.from_user.id)
    finished = await finish_focus_session(callback.from_user.id, session_id)

    if not finished:
        await callback.answer("Сессия уже завершена или не найдена.", show_alert=True)
        return

    method = active.method if active else "Focus"
    minutes = active.duration_minutes if active else 0
    await callback.message.edit_text(
        await build_focus_report_text(callback.from_user.id, method, minutes),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("focus_cancel:"))
async def focus_cancel(callback: types.CallbackQuery):
    session_id = int(callback.data.split(":", 1)[1])
    cancelled = await cancel_focus_session(callback.from_user.id, session_id)

    if not cancelled:
        await callback.answer("Сессия уже завершена или не найдена.", show_alert=True)
        return

    await callback.message.edit_text("Фокус-сессия отменена. Можно выбрать другой режим, когда будешь готов.")
    await callback.answer()


async def finish_focus_later(
    user_id: int,
    session_id: int,
    method: str,
    minutes: int,
    chat_id: int | None = None,
    message_id: int | None = None,
):
    await asyncio.sleep(minutes * 60)
    finished = await finish_focus_session(user_id, session_id)
    if finished:
        report = await build_focus_report_text(user_id, method, minutes)
        if chat_id and message_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=report,
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                pass

        await bot.send_message(
            user_id,
            report,
            parse_mode="HTML",
        )


@router.message(F.text == BTN_SUMMARY)
@router.message(Command("summary"))
async def summary(message: types.Message):
    data = await get_daily_summary(message.from_user.id)
    await message.answer(
        "📊 <b>Итог дня</b>\n\n"
        f"Готовые задачи: <b>{data['done_tasks']}</b>\n"
        f"Открытые задачи: <b>{data['open_tasks']}</b>\n"
        f"Фокус: <b>{data['focus_minutes']} мин</b>",
        parse_mode="HTML",
    )


@router.message(F.text == BTN_REVIEW)
@router.message(Command("review"))
async def review(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    data = await get_period_summary(message.from_user.id, days=7)
    next_task = await get_next_action_task(message.from_user.id)

    await message.answer(
        build_review_text(data, next_task),
        parse_mode="HTML",
    )


def build_review_text(data: dict, next_task) -> str:
    done = data["done_tasks"]
    created = data["created_tasks"]
    focus = data["focus_minutes"]
    avg_focus = round(focus / data["days"]) if data["days"] else 0
    completion = round(done / created * 100) if created else 0

    bars = build_week_bars(data["daily"])
    insight = review_insight(done, created, focus)

    lines = [
        "🧾 <b>Обзор недели</b>",
        "",
        f"Задачи: <b>{done}</b> выполнено из <b>{created}</b> созданных",
        f"Выполнение: <b>{completion}%</b>",
        f"Фокус: <b>{focus} мин</b> · в среднем {avg_focus} мин/день",
        "",
        f"<code>{bars}</code>",
        "",
        f"Вывод: {insight}",
    ]

    if next_task:
        lines.extend([
            "",
            "<b>Следующий шаг</b>",
            f"{matrix_badge(next_task)} {escape(next_task.title)}",
        ])

    return "\n".join(lines)


def build_week_bars(daily: list[dict]) -> str:
    values = [day["done_tasks"] + day["focus_minutes"] // 25 for day in daily]
    max_value = max(values, default=0)

    if max_value == 0:
        return " ".join("·" for _ in daily)

    bars = []
    for value in values:
        index = min(len(DAY_BAR) - 1, round(value / max_value * (len(DAY_BAR) - 1)))
        bars.append(DAY_BAR[index])

    return " ".join(bars)


def review_insight(done: int, created: int, focus: int) -> str:
    if done == 0 and focus == 0:
        return "неделя пока пустая. Начни с одной маленькой задачи или короткого фокуса."
    if focus >= 180 and done >= 5:
        return "хороший рабочий ритм. Сохраняй темп, но не забивай день задачами до краёв."
    if created > done * 2 and created >= 4:
        return "задач появляется больше, чем закрывается. Поможет матрица: оставь главное наверху."
    if focus < 45:
        return "добавь хотя бы одну короткую фокус-сессию. 15 минут уже достаточно."
    return "нормальная неделя. Следующий рост — меньше распыления и один главный шаг в день."


@router.message(F.text.startswith("/"))
async def unknown_command(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Не знаю такую команду. Нажми /help, чтобы посмотреть доступные.")


@router.message()
async def free_text(message: types.Message, state: FSMContext):
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("Пока сохраняю только текст. Отправь мысль или задачу сообщением — я положу её во входящие.")
        return
    if await handle_navigation_during_capture(message, state, text):
        return
    if is_command_text(text):
        await message.answer("Не знаю такую команду. Нажми /help, чтобы посмотреть доступные.")
        return

    await save_quick_tasks(message, state, text)
