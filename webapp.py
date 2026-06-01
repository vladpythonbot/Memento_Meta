import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN, HOST, PORT
from db import (
    cancel_focus_session,
    finish_focus_session,
    get_active_focus_session,
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
    app.router.add_get("/matrix", matrix_page)
    app.router.add_get("/focus", focus_page)
    app.router.add_get("/matrix/api/tasks", api_tasks)
    app.router.add_post("/matrix/api/tasks/{task_id}/matrix", api_update_matrix)
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
    return web.json_response({"ok": True, "service": "noto-memento"})


async def matrix_page(_request: web.Request) -> web.Response:
    return web.Response(text=MATRIX_HTML, content_type="text/html")


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

    if quadrant not in QUADRANTS:
        raise web.HTTPBadRequest(text="Unknown quadrant")

    important, urgent = QUADRANTS[quadrant]
    updated = await update_task_matrix(user_id, task_id, important, urgent)
    if not updated:
        raise web.HTTPNotFound(text="Task not found")

    return web.json_response({"ok": True})


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
    return web.json_response({"session": focus_session_payload(session), "id": session_id})


async def api_focus_finish(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    active = await get_active_focus_session(user_id)
    if not active:
        return web.json_response({"ok": False, "reason": "no_active_session"})

    finished = await finish_focus_session(user_id, active.id)
    return web.json_response({"ok": finished})


async def api_focus_cancel(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    active = await get_active_focus_session(user_id)
    if not active:
        return web.json_response({"ok": False, "reason": "no_active_session"})

    cancelled = await cancel_focus_session(user_id, active.id)
    return web.json_response({"ok": cancelled})


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


MATRIX_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Noto Memento · Matrix</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #f7f4ed;
      --ink: #171717;
      --muted: #6f6a60;
      --line: #ddd5c8;
      --card: #fffdf8;
      --urgent: #f5c2a6;
      --plan: #bddac7;
      --delegate: #c9d7f2;
      --drop: #ded8ce;
      --accent: #1f7a5a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app { padding: 18px; max-width: 900px; margin: 0 auto; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-end; margin-bottom: 14px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .hint { color: var(--muted); margin: 4px 0 0; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .cell {
      min-height: 210px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .cell[data-q="do"] { border-top: 5px solid var(--urgent); }
    .cell[data-q="plan"] { border-top: 5px solid var(--plan); }
    .cell[data-q="delegate"] { border-top: 5px solid var(--delegate); }
    .cell[data-q="drop"] { border-top: 5px solid var(--drop); }
    .cell-head { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; margin-bottom: 8px; }
    .cell-title { font-weight: 750; }
    .count { color: var(--muted); font-size: 13px; }
    .task {
      width: 100%;
      display: block;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      padding: 9px 10px;
      margin: 7px 0;
      text-align: left;
      font: inherit;
    }
    .task:active { transform: translateY(1px); }
    .task.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.16); }
    .inbox {
      margin-top: 12px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 12px;
      background: rgba(255,255,255,.45);
    }
    .actions {
      display: none;
      position: sticky;
      bottom: 0;
      margin: 14px -18px -18px;
      padding: 12px 18px 18px;
      background: rgba(247,244,237,.96);
      border-top: 1px solid var(--line);
    }
    .actions.visible { display: block; }
    .actions-title { font-weight: 700; margin-bottom: 8px; }
    .action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .action {
      border: 0;
      border-radius: 7px;
      padding: 11px 10px;
      font: inherit;
      font-weight: 700;
      color: var(--ink);
    }
    .action[data-q="do"] { background: var(--urgent); }
    .action[data-q="plan"] { background: var(--plan); }
    .action[data-q="delegate"] { background: var(--delegate); }
    .action[data-q="drop"] { background: var(--drop); }
    .empty { color: var(--muted); padding: 10px 0; }
    @media (max-width: 640px) {
      .app { padding: 14px; }
      header { display: block; }
      h1 { font-size: 22px; }
      .grid { gap: 8px; }
      .cell { min-height: 170px; padding: 10px; }
      .cell-title { font-size: 14px; }
      .task { font-size: 14px; padding: 8px; }
      .actions { margin-left: -14px; margin-right: -14px; margin-bottom: -14px; padding-left: 14px; padding-right: 14px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header>
      <div>
        <h1>Матрица</h1>
        <p class="hint">Выбери задачу и перенеси её в нужный квадрант.</p>
      </div>
    </header>

    <section class="grid" id="grid"></section>
    <section class="inbox" id="inbox"></section>

    <section class="actions" id="actions">
      <div class="actions-title" id="selectedTitle"></div>
      <div class="action-grid">
        <button class="action" data-q="do">Сделать</button>
        <button class="action" data-q="plan">Запланировать</button>
        <button class="action" data-q="delegate">Делегировать</button>
        <button class="action" data-q="drop">Убрать</button>
      </div>
    </section>
  </main>

  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    const labels = {
      do: ["Сделать", "важно и срочно"],
      plan: ["Запланировать", "важно, не срочно"],
      delegate: ["Делегировать", "срочно, не важно"],
      drop: ["Убрать", "не важно и не срочно"],
      inbox: ["Без квадранта", "нужно разобрать"]
    };
    const order = ["do", "plan", "delegate", "drop"];
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

    function taskButton(task) {
      const button = document.createElement("button");
      button.className = "task" + (selected?.id === task.id ? " selected" : "");
      button.textContent = task.title;
      button.onclick = () => selectTask(task);
      return button;
    }

    function selectTask(task) {
      selected = task;
      document.getElementById("selectedTitle").textContent = task.title;
      document.getElementById("actions").classList.add("visible");
      render();
    }

    function renderCell(quadrant) {
      const items = tasks.filter(task => task.quadrant === quadrant);
      const cell = document.createElement("section");
      cell.className = "cell";
      cell.dataset.q = quadrant;
      cell.innerHTML = `
        <div class="cell-head">
          <div>
            <div class="cell-title">${labels[quadrant][0]}</div>
            <div class="count">${labels[quadrant][1]}</div>
          </div>
          <div class="count">${items.length}</div>
        </div>
      `;
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Пусто";
        cell.appendChild(empty);
      }
      items.forEach(task => cell.appendChild(taskButton(task)));
      return cell;
    }

    function render() {
      const grid = document.getElementById("grid");
      grid.innerHTML = "";
      order.forEach(quadrant => grid.appendChild(renderCell(quadrant)));

      const inboxItems = tasks.filter(task => task.quadrant === "inbox");
      const inbox = document.getElementById("inbox");
      inbox.innerHTML = `<div class="cell-head"><div><div class="cell-title">Без квадранта</div><div class="count">разбери позже или сейчас</div></div><div class="count">${inboxItems.length}</div></div>`;
      if (!inboxItems.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Все задачи разнесены";
        inbox.appendChild(empty);
      }
      inboxItems.forEach(task => inbox.appendChild(taskButton(task)));
    }

    async function load() {
      try {
        const data = await api("/matrix/api/tasks");
        tasks = data.tasks;
        render();
      } catch (error) {
        document.getElementById("grid").innerHTML = `<section class="cell"><b>Не удалось открыть матрицу</b><p class="hint">Открой страницу из Telegram-кнопки Web App.</p></section>`;
      }
    }

    document.querySelectorAll(".action").forEach(button => {
      button.onclick = async () => {
        if (!selected) return;
        const quadrant = button.dataset.q;
        await api(`/matrix/api/tasks/${selected.id}/matrix`, {
          method: "POST",
          body: JSON.stringify({ quadrant })
        });
        selected.quadrant = quadrant;
        selected = null;
        document.getElementById("actions").classList.remove("visible");
        render();
      };
    });

    load();
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
  <title>Noto Memento · Focus</title>
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
    .app { max-width: 760px; margin: 0 auto; padding: 18px; }
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
    .methods { display: grid; gap: 8px; margin-top: 14px; }
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
    .controls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
    .control.finish { background: var(--accent-soft); font-weight: 800; text-align: center; }
    .control.cancel { background: var(--warm); font-weight: 800; text-align: center; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <main class="app">
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

    <section class="methods" id="methods">
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
        method.textContent = "Нет активной сессии";
        time.textContent = "00:00";
        status.textContent = "Готов начать";
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
      status.textContent = `${Math.round(progress * 100)}% · ${session.duration_minutes} мин`;
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
      button.onclick = async () => {
        const data = await api("/focus/api/start", {
          method: "POST",
          body: JSON.stringify({
            method: button.dataset.method,
            duration_minutes: Number(button.dataset.duration)
          })
        });
        session = data.session;
        render();
      };
    });

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
