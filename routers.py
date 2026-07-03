from html import escape

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import WEBAPP_URL
from db import (
    add_task,
    complete_task,
    ensure_user,
    get_daily_summary,
    get_matrix_tasks,
    get_next_action_task,
    get_open_tasks,
    get_period_summary,
    update_task_matrix,
)
from keyboards import BTN_APP, app_links_keyboard, app_url, main_keyboard


router = Router()
DAY_BAR = "▁▂▃▄▅▆▇█"


def is_command_text(text: str) -> bool:
    return text.strip().startswith("/")


def split_capture_items(text: str) -> list[str]:
    items = [line.strip(" -•\t") for line in text.splitlines()]
    return [item for item in items if len(item) >= 2]


async def save_quick_tasks(message: types.Message, state: FSMContext, text: str, silent: bool = False):
    if len(text) < 2:
        await message.answer("Слишком коротко. Напиши чуть подробнее.")
        return

    await ensure_user(message.from_user.id, message.from_user.first_name)
    await state.clear()

    items = split_capture_items(text) or [text]
    task_ids = [await add_task(message.from_user.id, item[:500]) for item in items]

    if silent:
        return

    if len(task_ids) == 1:
        await message.answer(
            f"Добавил во входящие:\n\n<b>{escape(items[0])}</b>",
            parse_mode="HTML",
            reply_markup=app_links_keyboard(WEBAPP_URL or None),
        )
        return

    await message.answer(
        f"Добавил во входящие: <b>{len(task_ids)}</b>\n\nРазберёшь их в панели.",
        parse_mode="HTML",
        reply_markup=app_links_keyboard(WEBAPP_URL or None),
    )


@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id, message.from_user.first_name)

    name = message.from_user.first_name or "друг"
    await message.answer(
        f"Привет, {escape(name)}.\n\n"
        "Я Memento Meta.\n\n"
        "Просто пиши сюда задачи, мысли или список. Я сложу всё во входящие, а разбор живёт в панели.",
        reply_markup=main_keyboard,
    )


@router.message(F.text == BTN_APP)
async def app_home(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    text, reply_markup = await build_today_view(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "Коротко:\n\n"
        "• отправь текст — он попадёт во входящие\n"
        "• несколько строк — несколько задач\n"
        "• 🧭 Панель — разбор, матрица, готово и удалить"
    )


@router.message(Command("settings"))
async def settings(message: types.Message):
    await message.answer(
        "Настроек почти нет. Так и задумано.\n\n"
        "Язык: русский\n"
        "Основной сценарий: текст → входящие → матрица"
    )


@router.message(Command("task"))
async def quick_task(message: types.Message, state: FSMContext):
    text = message.text.partition(" ")[2].strip() if message.text else ""
    if not text:
        await message.answer("Напиши так: <code>/task разобрать почту</code>", parse_mode="HTML")
        return

    await save_quick_tasks(message, state, text, silent=True)


@router.message(Command("today"))
async def today(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    text, reply_markup = await build_today_view(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.message(Command("matrix", "eisenhower"))
async def matrix(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    text, reply_markup = await build_matrix_view(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.message(Command("summary"))
async def summary(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    data = await get_daily_summary(message.from_user.id)
    await message.answer(
        "📊 <b>Сегодня</b>\n\n"
        f"Добавлено: <b>{data['created_tasks']}</b>\n"
        f"Готово: <b>{data['done_tasks']}</b>\n"
        f"Открыто всего: <b>{data['open_tasks']}</b>",
        parse_mode="HTML",
        reply_markup=app_links_keyboard(WEBAPP_URL or None),
    )


@router.message(Command("review"))
async def review(message: types.Message):
    await ensure_user(message.from_user.id, message.from_user.first_name)
    data = await get_period_summary(message.from_user.id, days=7)
    next_task = await get_next_action_task(message.from_user.id)
    await message.answer(build_review_text(data, next_task), parse_mode="HTML")


async def build_today_view(user_id: int, completed_task=None):
    tasks = await get_open_tasks(user_id, limit=10)
    summary = await get_daily_summary(user_id)

    lines = ["📝 <b>Задачи</b>", ""]

    if completed_task:
        lines.append(f"☑ <s>{escape(completed_task.title)}</s>")
        lines.append("")

    if tasks:
        lines.append("Нажми на задачу ниже, чтобы закрыть её.")
    else:
        lines.append("Открытых задач нет. Просто напиши новую задачу сообщением.")

    lines.append("")
    lines.append(f"Итог: {summary['done_tasks']} готово · {summary['created_tasks']} добавлено сегодня")
    return "\n".join(lines), build_tasks_keyboard(tasks)


def build_tasks_keyboard(tasks) -> types.InlineKeyboardMarkup | None:
    rows = []
    for task in tasks:
        title = compact_button_text(task.title)
        rows.append([types.InlineKeyboardButton(text=f"☐ {title}", callback_data=f"task_done:{task.id}")])

    url = app_url(WEBAPP_URL or None)
    if url:
        rows.append([types.InlineKeyboardButton(text="Открыть Mini App", web_app=types.WebAppInfo(url=url))])

    if not rows:
        return None
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def compact_button_text(text: str, limit: int = 58) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit - 1].rstrip()}…"


async def build_matrix_view(user_id: int):
    tasks = await get_matrix_tasks(user_id)
    counts = count_matrix_tasks(tasks)

    if not tasks:
        return "\n".join([
            "🧭 <b>Матрица</b>",
            "",
            "Открытых задач пока нет. Просто напиши задачу в чат.",
        ]), app_links_keyboard(WEBAPP_URL or None)

    lines = [
        "🧭 <b>Матрица</b>",
        "",
        f"Входящие: <b>{counts['inbox']}</b>",
        f"Сделать: <b>{counts['do']}</b>",
        f"План: <b>{counts['plan']}</b>",
        f"Делегировать: <b>{counts['delegate']}</b>",
        f"Убрать: <b>{counts['drop']}</b>",
        "",
        "Открой панель, чтобы перетаскивать задачи.",
    ]
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
    current_tasks = await get_open_tasks(callback.from_user.id, limit=200)
    completed_task = next((task for task in current_tasks if task.id == task_id), None)
    done = await complete_task(callback.from_user.id, task_id)

    if not done:
        await callback.answer("Задача уже закрыта или не найдена.", show_alert=True)
        return

    text, reply_markup = await build_today_view(callback.from_user.id, completed_task=completed_task)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await callback.answer("Готово")


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

    if quadrant not in mapping:
        await callback.answer("Неизвестный квадрант.", show_alert=True)
        return

    important, urgent = mapping[quadrant]
    updated = await update_task_matrix(callback.from_user.id, task_id, important, urgent)
    if not updated:
        await callback.answer("Задача не найдена или уже закрыта.", show_alert=True)
        return

    text, reply_markup = await build_matrix_view(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    await callback.answer()


def build_review_text(data: dict, next_task) -> str:
    done = data["done_tasks"]
    created = data["created_tasks"]
    completion = round(done / created * 100) if created else 0
    bars = build_week_bars(data["daily"])

    lines = [
        "🧾 <b>Обзор недели</b>",
        "",
        f"Задачи: <b>{done}</b> выполнено из <b>{created}</b> созданных",
        f"Выполнение: <b>{completion}%</b>",
        "",
        f"<code>{bars}</code>",
        "",
        f"Вывод: {review_insight(done, created)}",
    ]

    if next_task:
        lines.extend(["", "<b>Первым делом</b>", f"{matrix_badge(next_task)} {escape(next_task.title)}"])

    return "\n".join(lines)


def build_week_bars(daily: list[dict]) -> str:
    values = [day["done_tasks"] for day in daily]
    max_value = max(values, default=0)
    if max_value == 0:
        return " ".join("·" for _ in daily)

    bars = []
    for value in values:
        index = min(len(DAY_BAR) - 1, round(value / max_value * (len(DAY_BAR) - 1)))
        bars.append(DAY_BAR[index])
    return " ".join(bars)


def review_insight(done: int, created: int) -> str:
    if done == 0 and created == 0:
        return "неделя пустая. Начни с одного пункта во входящих."
    if created > done * 2 and created >= 4:
        return "задач появляется больше, чем закрывается. Разбери входящие и убери лишнее."
    if done >= created and created > 0:
        return "хороший темп. Главное — не превращать входящие в склад."
    return "нормально. Следующий шаг — выбрать одну главную задачу и закрыть её."


@router.message(F.text.startswith("/"))
async def unknown_command(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Не знаю такую команду. Нажми /help.")


@router.message()
async def free_text(message: types.Message, state: FSMContext):
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("Пока сохраняю только текст. Отправь задачу или мысль сообщением.")
        return
    if is_command_text(text):
        await message.answer("Не знаю такую команду. Нажми /help.")
        return

    await save_quick_tasks(message, state, text, silent=True)
