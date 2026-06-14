import asyncio
import hashlib
import hmac
import json
from html import escape
from urllib.parse import parse_qsl

from aiohttp import web

from bot import bot
from config import BOT_TOKEN, HOST, PORT
from db import (
    add_task,
    cancel_focus_session,
    clear_task_matrix,
    complete_task,
    delete_task,
    finish_focus_session,
    get_active_focus_session,
    get_daily_summary,
    get_matrix_tasks,
    start_focus_session,
    update_task_matrix,
)


QUADRANTS = {
    "do": (True, True),
    "plan": (True, False),
    "delegate": (False, True),
    "drop": (False, False),
}


async def start_webapp() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/app", matrix_page)
    app.router.add_get("/matrix", matrix_page)
    app.router.add_get("/focus", focus_page)
    app.router.add_get("/matrix/api/tasks", api_tasks)
    app.router.add_post("/matrix/api/tasks", api_create_task)
    app.router.add_post("/matrix/api/tasks/{task_id}/matrix", api_update_matrix)
    app.router.add_post("/matrix/api/tasks/{task_id}/done", api_complete_task)
    app.router.add_delete("/matrix/api/tasks/{task_id}", api_delete_task)
    app.router.add_get("/app/api/summary", api_summary)
    app.router.add_get("/focus/api/session", api_focus_session)
    app.router.add_post("/focus/api/start", api_focus_start)
    app.router.add_post("/focus/api/finish", api_focus_finish)
    app.router.add_post("/focus/api/cancel", api_focus_cancel)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    return runner


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "memento-meta"})


async def matrix_page(_request: web.Request) -> web.Response:
    return web.Response(text=V5_APP_HTML, content_type="text/html")


async def focus_page(_request: web.Request) -> web.Response:
    return web.Response(text=FOCUS_HTML, content_type="text/html")


async def api_tasks(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    tasks = await get_matrix_tasks(user_id, limit=80)
    return web.json_response({
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "important": task.important,
                "urgent": task.urgent,
                "quadrant": task_quadrant(task.important, task.urgent),
            }
            for task in tasks
        ]
    })


async def api_update_matrix(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    task_id = int(request.match_info["task_id"])
    payload = await request.json()
    quadrant = payload.get("quadrant")

    if quadrant == "inbox":
        updated = await clear_task_matrix(user_id, task_id)
        if not updated:
            raise web.HTTPNotFound(text="Task not found")
        return web.json_response({"ok": True})

    if quadrant not in QUADRANTS:
        raise web.HTTPBadRequest(text="Unknown quadrant")

    important, urgent = QUADRANTS[quadrant]
    updated = await update_task_matrix(user_id, task_id, important, urgent)
    if not updated:
        raise web.HTTPNotFound(text="Task not found")

    return web.json_response({"ok": True})


async def api_create_task(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    payload = await request.json()
    title = str(payload.get("title", "")).strip()
    quadrant = payload.get("quadrant")

    if len(title) < 2:
        raise web.HTTPBadRequest(text="Task title is too short")

    task_id = await add_task(user_id, title[:500])

    if quadrant in QUADRANTS:
        important, urgent = QUADRANTS[quadrant]
        await update_task_matrix(user_id, task_id, important, urgent)

    return web.json_response({"ok": True, "id": task_id})


async def api_complete_task(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    task_id = int(request.match_info["task_id"])
    completed = await complete_task(user_id, task_id)
    if not completed:
        raise web.HTTPNotFound(text="Task not found")

    return web.json_response({"ok": True})


async def api_delete_task(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    task_id = int(request.match_info["task_id"])
    deleted = await delete_task(user_id, task_id)
    if not deleted:
        raise web.HTTPNotFound(text="Task not found")

    return web.json_response({"ok": True})


async def api_summary(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    return web.json_response(await get_daily_summary(user_id))


async def api_focus_session(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    session = await get_active_focus_session(user_id)
    return web.json_response({"session": focus_session_payload(session)})


async def api_focus_start(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    active = await get_active_focus_session(user_id)
    if active:
        return web.json_response({"session": focus_session_payload(active), "already_active": True})

    payload = await request.json()
    method = payload.get("method", "Pomodoro")
    duration = int(payload.get("duration_minutes", 25))
    session_id = await start_focus_session(user_id, method, duration)
    session = await get_active_focus_session(user_id)
    pinned_message = await send_focus_timer_message(user_id, session)
    asyncio.create_task(
        finish_focus_later(
            user_id,
            session_id,
            method,
            duration,
            message_id=pinned_message.message_id if pinned_message else None,
        )
    )
    return web.json_response({"session": focus_session_payload(session), "id": session_id})


async def api_focus_finish(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    active = await get_active_focus_session(user_id)
    if not active:
        return web.json_response({"ok": False, "reason": "no_active_session"})

    finished = await finish_focus_session(user_id, active.id)
    if finished:
        await send_focus_report(user_id, active.method, active.duration_minutes)
    return web.json_response({"ok": finished})


async def api_focus_cancel(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    active = await get_active_focus_session(user_id)
    if not active:
        return web.json_response({"ok": False, "reason": "no_active_session"})

    cancelled = await cancel_focus_session(user_id, active.id)
    return web.json_response({"ok": cancelled})


async def finish_focus_later(
    user_id: int,
    session_id: int,
    method: str,
    duration: int,
    message_id: int | None = None,
) -> None:
    await asyncio.sleep(duration * 60)
    finished = await finish_focus_session(user_id, session_id)
    if finished:
        await send_focus_report(user_id, method, duration, message_id=message_id)


def build_focus_timer_text(session) -> str:
    return (
        f"🎯 <b>{escape(session.method)}</b>\n\n"
        "<code>□□□□□□□□□□</code> <b>0%</b>\n"
        f"Длительность: <b>{session.duration_minutes} мин</b>\n"
        "Прошло: <b>0 мин</b>\n"
        f"Осталось: <b>{session.duration_minutes} мин</b>\n\n"
        "Это закреплённый таймер. В конце он станет отчётом."
    )


async def send_focus_timer_message(user_id: int, session):
    if not session:
        return None

    message = await bot.send_message(user_id, build_focus_timer_text(session), parse_mode="HTML")
    try:
        await bot.pin_chat_message(chat_id=user_id, message_id=message.message_id, disable_notification=True)
    except Exception:
        pass
    return message


async def send_focus_report(user_id: int, method: str, duration: int, message_id: int | None = None) -> None:
    summary = await get_daily_summary(user_id)
    report = (
        "✅ <b>Концентрация завершена</b>\n\n"
        f"Режим: <b>{escape(method)}</b>\n"
        f"Длительность: <b>{duration} мин</b>\n\n"
        "📊 <b>Итог дня</b>\n"
        f"Готовые задачи: <b>{summary['done_tasks']}</b>\n"
        f"Открытые задачи: <b>{summary['open_tasks']}</b>\n"
        f"Фокус: <b>{summary['focus_minutes']} мин</b>\n\n"
        "Сделай короткую паузу и выбери следующий шаг."
    )
    if message_id:
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=message_id, text=report, parse_mode="HTML")
        except Exception:
            pass

    await bot.send_message(user_id, report, parse_mode="HTML")


def focus_session_payload(session) -> dict | None:
    if not session:
        return None

    return {
        "id": session.id,
        "method": session.method,
        "duration_minutes": session.duration_minutes,
        "status": session.status,
        "started_at": session.started_at,
        "finished_at": session.finished_at,
    }


def user_id_from_request(request: web.Request) -> int:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        raise web.HTTPUnauthorized(text="Missing Telegram init data")

    data = validate_init_data(init_data)
    user = json.loads(data.get("user", "{}"))
    user_id = user.get("id")
    if not user_id:
        raise web.HTTPUnauthorized(text="Missing Telegram user")

    return int(user_id)


def validate_init_data(init_data: str) -> dict[str, str]:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise web.HTTPUnauthorized(text="Missing hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise web.HTTPUnauthorized(text="Bad Telegram init data")

    return pairs


def task_quadrant(important: bool | None, urgent: bool | None) -> str:
    if important is True and urgent is True:
        return "do"
    if important is True and urgent is False:
        return "plan"
    if important is False and urgent is True:
        return "delegate"
    if important is False and urgent is False:
        return "drop"
    return "inbox"


V5_APP_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memento Meta · v5</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #f7f3ea;
      --ink: #171717;
      --muted: #6d665d;
      --line: #ded2c2;
      --card: #fffdf8;
      --soft: #fbf6ec;
      --accent: #1f7a5a;
      --urgent: #ef9d77;
      --plan: #77b98f;
      --delegate: #8aa9de;
      --drop: #bfb4a4;
      --note: #f2c766;
      --danger: #cf6655;
      --shadow: 0 10px 28px rgba(37, 29, 19, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(180deg, #fffaf2 0%, var(--bg) 100%);
      color: var(--ink);
      font: 15px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app { max-width: 1180px; margin: 0 auto; padding: 16px; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-end; margin-bottom: 12px; }
    h1 { margin: 0; font-size: 25px; letter-spacing: 0; }
    .hint { color: var(--muted); margin: 4px 0 0; }
    .nav { display: flex; gap: 7px; overflow-x: auto; padding-bottom: 6px; margin-bottom: 10px; }
    .tab {
      border: 1px solid var(--line);
      background: rgba(255,255,255,.78);
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 11px;
      font: inherit;
      font-weight: 800;
      white-space: nowrap;
      cursor: pointer;
      text-decoration: none;
    }
    .tab.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    .composer, .panel, .cell {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .composer { padding: 10px; margin-bottom: 12px; }
    .input-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 11px 12px;
      font: inherit;
      outline: none;
    }
    input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.12); }
    .primary {
      border: 0;
      border-radius: 7px;
      padding: 0 16px;
      min-height: 42px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 850;
      cursor: pointer;
    }
    .summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }
    .metric { border: 1px solid var(--line); background: rgba(255,255,255,.68); border-radius: 8px; padding: 9px; }
    .metric b { display: block; font-size: 21px; line-height: 1; }
    .metric span { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .split { display: grid; grid-template-columns: minmax(260px, .85fr) minmax(0, 1.4fr); gap: 12px; }
    .panel { padding: 12px; }
    .panel-title { font-weight: 900; font-size: 17px; margin-bottom: 4px; }
    .muted { color: var(--muted); }
    .list { margin-top: 10px; }
    .task {
      width: 100%;
      display: block;
      border: 1px solid var(--line);
      border-left: 4px solid var(--line);
      border-radius: 7px;
      background: #fff;
      padding: 10px;
      margin: 7px 0;
      color: var(--ink);
      font: inherit;
      text-align: left;
      cursor: pointer;
      touch-action: none;
      user-select: none;
    }
    .task[data-q="do"] { border-left-color: var(--urgent); }
    .task[data-q="plan"] { border-left-color: var(--plan); }
    .task[data-q="delegate"] { border-left-color: var(--delegate); }
    .task[data-q="drop"] { border-left-color: var(--drop); }
    .task.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.14); }
    .task.dragging { opacity: .35; }
    .task-ghost {
      position: fixed;
      z-index: 80;
      width: min(280px, calc(100vw - 30px));
      pointer-events: none;
      transform: translate(-50%, -50%) rotate(-1deg);
      box-shadow: 0 18px 34px rgba(23,23,23,.16);
    }
    .task-title { display: block; font-weight: 780; overflow-wrap: anywhere; }
    .task-meta { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
    .task-actions { display: none; grid-template-columns: 1fr 1fr; gap: 7px; margin-top: 8px; }
    .task.selected .task-actions { display: grid; }
    .action {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      padding: 8px;
      font: inherit;
      font-weight: 850;
      cursor: pointer;
    }
    .action.done { background: var(--accent); border-color: var(--accent); color: #fff; }
    .action.delete { color: var(--danger); border-color: rgba(207,102,85,.45); }
    .matrix {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .cell { min-height: 230px; padding: 11px; }
    .cell[data-q="do"] { border-top: 5px solid var(--urgent); }
    .cell[data-q="plan"] { border-top: 5px solid var(--plan); }
    .cell[data-q="delegate"] { border-top: 5px solid var(--delegate); }
    .cell[data-q="drop"] { border-top: 5px solid var(--drop); }
    .cell.drop-target, .panel.drop-target { background: #f4fff6; border-color: rgba(31,122,90,.55); }
    .cell-head { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
    .cell-title { font-weight: 900; }
    .count { color: var(--muted); font-size: 13px; }
    .focus-link {
      display: inline-block;
      text-align: center;
      text-decoration: none;
      border-radius: 8px;
      padding: 12px 14px;
      background: var(--accent);
      color: #fff;
      font-weight: 900;
    }
    .empty { color: var(--muted); padding: 10px 0; }
    @media (max-width: 760px) {
      .app { padding: 12px; }
      header { display: block; }
      h1 { font-size: 22px; }
      .input-row, .split { grid-template-columns: 1fr; }
      .summary { grid-template-columns: repeat(4, minmax(68px, 1fr)); overflow-x: auto; }
      .matrix { grid-template-columns: repeat(2, minmax(145px, 1fr)); overflow-x: auto; }
      .cell { min-height: 170px; padding: 9px; }
      .task { padding: 8px; font-size: 14px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header>
      <div>
        <h1>Memento Meta v5</h1>
        <p class="hint">Входящие, матрица и задачи на одной странице.</p>
      </div>
    </header>

    <nav class="nav">
      <button class="tab active" type="button">Матрица</button>
      <a class="tab" href="/focus?v=5">Фокус</a>
    </nav>

    <section class="composer">
      <div class="input-row">
        <input id="taskInput" maxlength="500" placeholder="Новая задача">
        <button class="primary" id="addTask">Во входящие</button>
      </div>
    </section>

    <section class="summary" id="summary"></section>

    <section class="split">
      <section class="panel" id="incomingPanel">
        <div class="panel-title">Входящие</div>
        <div class="muted">Всё, что пришло из Telegram и ещё не разобрано. Сюда можно вернуть задачу из матрицы.</div>
        <div class="list" id="incomingList"></div>
      </section>
      <section>
      <section class="matrix" id="matrixGrid"></section>
      </section>
    </section>
  </main>

  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    const labels = {
      do: ["Сделать", "важно и срочно"],
      plan: ["План", "важно, не срочно"],
      delegate: ["Делегировать", "срочно, не важно"],
      drop: ["Убрать", "не важно и не срочно"],
      inbox: ["Входящие", "нужно разобрать"]
    };
    const order = ["do", "plan", "delegate", "drop"];
    const dropOrder = ["inbox", ...order];
    let tasks = [];
    let selected = null;

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": tg?.initData || "",
          ...(options.headers || {})
        }
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    function quadrant(task) {
      return task.quadrant || "inbox";
    }

    function taskCard(task) {
      const card = document.createElement("article");
      card.className = "task" + (selected?.id === task.id ? " selected" : "");
      card.dataset.q = quadrant(task);
      card.draggable = true;

      const title = document.createElement("span");
      title.className = "task-title";
      title.textContent = task.title;

      const meta = document.createElement("span");
      meta.className = "task-meta";
      meta.textContent = quadrant(task) === "inbox" ? "из входящих" : labels[quadrant(task)][1];

      const actions = document.createElement("div");
      actions.className = "task-actions";

      const done = document.createElement("button");
      done.className = "action done";
      done.type = "button";
      done.textContent = "Готово";
      done.onclick = event => {
        event.stopPropagation();
        completeTask(task);
      };

      const remove = document.createElement("button");
      remove.className = "action delete";
      remove.type = "button";
      remove.textContent = "Удалить";
      remove.onclick = event => {
        event.stopPropagation();
        deleteTask(task);
      };

      actions.append(done, remove);
      card.append(title, meta, actions);
      card.addEventListener("dragstart", event => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", String(task.id));
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => clearTargets());
      card.addEventListener("pointerdown", event => startPointerDrag(event, task, card));
      return card;
    }

    function matrixCell(q, source = tasks) {
      const items = source.filter(task => quadrant(task) === q);
      const cell = document.createElement("section");
      cell.className = "cell";
      cell.dataset.q = q;
      cell.innerHTML = `<div class="cell-head"><div><div class="cell-title">${labels[q][0]}</div><div class="count">${labels[q][1]}</div></div><div class="count">${items.length}</div></div>`;
      cell.addEventListener("dragover", event => {
        event.preventDefault();
        cell.classList.add("drop-target");
      });
      cell.addEventListener("dragleave", event => {
        if (!cell.contains(event.relatedTarget)) cell.classList.remove("drop-target");
      });
      cell.addEventListener("drop", async event => {
        event.preventDefault();
        clearTargets();
        const task = tasks.find(item => item.id === Number(event.dataTransfer.getData("text/plain")));
        if (task) await moveTask(task, q);
      });
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Пусто";
        cell.appendChild(empty);
      }
      items.forEach(task => cell.appendChild(taskCard(task)));
      return cell;
    }

    function renderTasks(container, items, emptyText) {
      container.innerHTML = "";
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = emptyText;
        container.appendChild(empty);
        return;
      }
      items.forEach(task => container.appendChild(taskCard(task)));
    }

    function renderSummary(summary = {}) {
      const inbox = tasks.filter(task => quadrant(task) === "inbox").length;
      const open = tasks.length;
      const matrixed = tasks.filter(task => quadrant(task) !== "inbox").length;
      document.getElementById("summary").innerHTML = [
        ["Входящие", inbox],
        ["Открыто", open],
        ["В матрице", matrixed],
        ["Фокус", `${summary.focus_minutes || 0}м`],
      ].map(([label, value]) => `<div class="metric"><b>${value}</b><span>${label}</span></div>`).join("");
    }

    function render() {
      const inboxItems = tasks.filter(task => quadrant(task) === "inbox");
      renderTasks(document.getElementById("incomingList"), inboxItems, "Входящие пустые");

      const matrixGrid = document.getElementById("matrixGrid");
      matrixGrid.innerHTML = "";
      order.forEach(q => matrixGrid.appendChild(matrixCell(q, tasks)));
      setupIncomingDrop();
    }

    async function load() {
      const [taskData, summary] = await Promise.all([
        api("/matrix/api/tasks"),
        api("/app/api/summary")
      ]);
      tasks = taskData.tasks;
      renderSummary(summary);
      render();
    }

    async function createTask() {
      const input = document.getElementById("taskInput");
      const title = input.value.trim();
      if (title.length < 2) {
        input.focus();
        return;
      }
      await api("/matrix/api/tasks", { method: "POST", body: JSON.stringify({ title }) });
      input.value = "";
      selected = null;
      await load();
    }

    async function moveTask(task, q) {
      await api(`/matrix/api/tasks/${task.id}/matrix`, { method: "POST", body: JSON.stringify({ quadrant: q }) });
      task.quadrant = q;
      selected = null;
      render();
    }

    async function completeTask(task) {
      await api(`/matrix/api/tasks/${task.id}/done`, { method: "POST" });
      tasks = tasks.filter(item => item.id !== task.id);
      selected = null;
      render();
    }

    async function deleteTask(task) {
      await api(`/matrix/api/tasks/${task.id}`, { method: "DELETE" });
      tasks = tasks.filter(item => item.id !== task.id);
      selected = null;
      render();
    }

    function clearTargets() {
      document.querySelectorAll(".drop-target").forEach(item => item.classList.remove("drop-target"));
      document.querySelectorAll(".dragging").forEach(item => item.classList.remove("dragging"));
    }

    function dropTargetAt(x, y) {
      const element = document.elementFromPoint(x, y);
      const target = element?.closest?.(".cell, #incomingPanel");
      return dropOrder.includes(target?.dataset?.q) ? target : null;
    }

    function setupIncomingDrop() {
      const panel = document.getElementById("incomingPanel");
      panel.dataset.q = "inbox";
      panel.ondragover = event => {
        event.preventDefault();
        panel.classList.add("drop-target");
      };
      panel.ondragleave = event => {
        if (!panel.contains(event.relatedTarget)) panel.classList.remove("drop-target");
      };
      panel.ondrop = async event => {
        event.preventDefault();
        clearTargets();
        const task = tasks.find(item => item.id === Number(event.dataTransfer.getData("text/plain")));
        if (task) await moveTask(task, "inbox");
      };
    }

    function startPointerDrag(event, task, card) {
      if (event.button !== undefined && event.button !== 0) return;
      if (event.target.closest(".action")) return;

      const startX = event.clientX;
      const startY = event.clientY;
      let dragging = false;
      let ghost = null;

      const move = moveEvent => {
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (!dragging && Math.hypot(dx, dy) < 8) return;
        moveEvent.preventDefault();

        if (!dragging) {
          dragging = true;
          card.classList.add("dragging");
          ghost = card.cloneNode(true);
          ghost.classList.add("task-ghost");
          ghost.querySelectorAll("button").forEach(button => button.remove());
          document.body.appendChild(ghost);
        }

        ghost.style.left = `${moveEvent.clientX}px`;
        ghost.style.top = `${moveEvent.clientY}px`;
        clearTargets();
        dropTargetAt(moveEvent.clientX, moveEvent.clientY)?.classList.add("drop-target");
      };

      const end = async endEvent => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", cancel);
        ghost?.remove();
        card.classList.remove("dragging");
        const target = dropTargetAt(endEvent.clientX, endEvent.clientY);
        clearTargets();

        if (dragging && target) {
          await moveTask(task, target.dataset.q);
          tg?.HapticFeedback?.impactOccurred?.("light");
        } else if (!dragging) {
          selected = selected?.id === task.id ? null : task;
          render();
        }
      };

      const cancel = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", cancel);
        ghost?.remove();
        clearTargets();
      };

      window.addEventListener("pointermove", move, { passive: false });
      window.addEventListener("pointerup", end);
      window.addEventListener("pointercancel", cancel);
    }

    document.getElementById("addTask").onclick = createTask;
    document.getElementById("taskInput").addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        createTask();
      }
    });
    load().catch(() => {
      document.querySelector(".app").innerHTML = "<section class='panel'><b>Открой панель из Telegram</b><p class='hint'>Так Web App получает доступ к твоим данным.</p></section>";
    });
  </script>
</body>
</html>
"""


FOCUS_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memento Meta · Focus</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #f7f4ed;
      --ink: #171717;
      --muted: #706b62;
      --line: #ded6ca;
      --card: #fffdf8;
      --accent: #1f7a5a;
      --accent-soft: #bddac7;
      --warm: #f5c2a6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app { max-width: 820px; margin: 0 auto; padding: 18px; }
    .nav { display: flex; gap: 8px; margin-bottom: 14px; }
    .nav a {
      text-decoration: none;
      color: var(--ink);
      background: rgba(255,255,255,.72);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 11px;
      font-weight: 750;
      font-size: 14px;
    }
    .nav a.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    h1 { margin: 0; font-size: 24px; }
    .hint { color: var(--muted); margin: 5px 0 18px; }
    .timer {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 20px;
      display: grid;
      place-items: center;
      min-height: 330px;
    }
    .ring {
      width: min(72vw, 280px);
      aspect-ratio: 1;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: conic-gradient(var(--accent) var(--progress, 0deg), #e8e0d4 0);
      position: relative;
    }
    .ring::after {
      content: "";
      position: absolute;
      inset: 14px;
      border-radius: 50%;
      background: var(--card);
    }
    .center {
      position: relative;
      z-index: 1;
      text-align: center;
    }
    .method { font-weight: 800; margin-bottom: 6px; }
    .time { font-size: 46px; font-weight: 850; line-height: 1; }
    .status { color: var(--muted); margin-top: 8px; }
    .focus-input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      padding: 12px;
      font: inherit;
      outline: none;
      margin-top: 14px;
    }
    .focus-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.12); }
    .methods { display: grid; gap: 8px; margin-top: 10px; }
    .method-button, .control {
      border: 0;
      border-radius: 8px;
      padding: 13px 12px;
      font: inherit;
      color: var(--ink);
      background: var(--card);
      border: 1px solid var(--line);
      text-align: left;
    }
    .method-button strong { display: block; font-size: 16px; }
    .method-button span { color: var(--muted); }
    .method-button.primary { border-color: var(--accent); background: #f3fbf6; }
    .duration-row { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; margin-top: 10px; }
    input[type="range"] { width: 100%; accent-color: var(--accent); }
    .duration-value { font-weight: 850; min-width: 68px; text-align: right; }
    .start-button {
      width: 100%;
      border: 0;
      border-radius: 8px;
      padding: 13px 12px;
      margin-top: 10px;
      font: inherit;
      font-weight: 850;
      color: #fff;
      background: var(--accent);
    }
    .controls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
    .control.finish { background: var(--accent-soft); font-weight: 800; text-align: center; }
    .control.cancel { background: var(--warm); font-weight: 800; text-align: center; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <main class="app">
    <nav class="nav">
      <a href="/matrix?v=5">Матрица</a>
      <a class="active" href="/focus?v=5">Фокус</a>
    </nav>

    <h1>Фокус</h1>
    <p class="hint">Выбери режим и держи одно дело в центре.</p>

    <section class="timer">
      <div class="ring" id="ring">
        <div class="center">
          <div class="method" id="method">Нет активной сессии</div>
          <div class="time" id="time">00:00</div>
          <div class="status" id="status">Готов начать</div>
        </div>
      </div>
    </section>

    <section id="methods">
      <input class="focus-input" id="focusInput" maxlength="120" placeholder="Над чем работаем">
      <div class="methods">
      <button class="method-button primary" data-method="Pomodoro" data-duration="25">
        <strong>Pomodoro · 25 мин</strong>
        <span>Обычная рабочая задача</span>
      </button>
      <button class="method-button" data-method="Short Focus" data-duration="15">
        <strong>Short Focus · 15 мин</strong>
        <span>Короткий рывок без давления</span>
      </button>
      <button class="method-button" data-method="Deep Work" data-duration="90">
        <strong>Deep Work · 90 мин</strong>
        <span>Глубокая работа без переключений</span>
      </button>
      </div>
      <div class="duration-row">
        <input id="durationRange" type="range" min="5" max="120" step="5" value="25">
        <div class="duration-value" id="durationValue">25 мин</div>
      </div>
      <button class="start-button" id="startFocus">Начать фокус</button>
    </section>

    <section class="controls hidden" id="controls">
      <button class="control finish" id="finish">Завершить</button>
      <button class="control cancel" id="cancel">Отменить</button>
    </section>
  </main>

  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    let session = null;
    let timer = null;
    let selectedMethod = "Pomodoro";
    let selectedDuration = 25;
    let focusTarget = "";

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": tg?.initData || "",
          ...(options.headers || {})
        }
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    function format(seconds) {
      const m = Math.floor(seconds / 60).toString().padStart(2, "0");
      const s = Math.max(0, seconds % 60).toString().padStart(2, "0");
      return `${m}:${s}`;
    }

    function render() {
      const ring = document.getElementById("ring");
      const method = document.getElementById("method");
      const time = document.getElementById("time");
      const status = document.getElementById("status");
      const methods = document.getElementById("methods");
      const controls = document.getElementById("controls");

      if (!session) {
        ring.style.setProperty("--progress", "0deg");
        method.textContent = selectedMethod;
        time.textContent = format(selectedDuration * 60);
        status.textContent = (document.getElementById("focusInput").value || "Готов начать").trim();
        methods.classList.remove("hidden");
        controls.classList.add("hidden");
        return;
      }

      const started = new Date(session.started_at);
      const total = session.duration_minutes * 60;
      const elapsed = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
      const left = Math.max(0, total - elapsed);
      const progress = Math.min(1, elapsed / total);

      ring.style.setProperty("--progress", `${Math.round(progress * 360)}deg`);
      method.textContent = session.method;
      time.textContent = format(left);
      status.textContent = focusTarget || `${Math.round(progress * 100)}% · ${session.duration_minutes} мин`;
      methods.classList.add("hidden");
      controls.classList.remove("hidden");
    }

    async function load() {
      try {
        const data = await api("/focus/api/session");
        session = data.session;
        render();
        if (timer) clearInterval(timer);
        timer = setInterval(render, 1000);
      } catch (error) {
        document.getElementById("status").textContent = "Открой фокус из Telegram-кнопки Web App.";
      }
    }

    document.querySelectorAll(".method-button").forEach(button => {
      button.onclick = () => {
        selectedMethod = button.dataset.method;
        selectedDuration = Number(button.dataset.duration);
        document.getElementById("durationRange").value = selectedDuration;
        document.getElementById("durationValue").textContent = `${selectedDuration} мин`;
        document.querySelectorAll(".method-button").forEach(item => item.classList.remove("primary"));
        button.classList.add("primary");
        render();
      };
    });

    document.getElementById("durationRange").oninput = event => {
      selectedDuration = Number(event.target.value);
      document.getElementById("durationValue").textContent = `${selectedDuration} мин`;
      render();
    };

    document.getElementById("focusInput").oninput = render;

    document.getElementById("startFocus").onclick = async () => {
        focusTarget = document.getElementById("focusInput").value.trim();
        const data = await api("/focus/api/start", {
          method: "POST",
          body: JSON.stringify({
            method: selectedMethod,
            duration_minutes: selectedDuration
          })
        });
        session = data.session;
        render();
    };

    document.getElementById("finish").onclick = async () => {
      await api("/focus/api/finish", { method: "POST", body: "{}" });
      session = null;
      render();
    };

    document.getElementById("cancel").onclick = async () => {
      await api("/focus/api/cancel", { method: "POST", body: "{}" });
      session = null;
      render();
    };

    load();
  </script>
</body>
</html>
"""

