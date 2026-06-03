import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN, HOST, PORT
from db import (
    add_task,
    cancel_focus_session,
    complete_task,
    finish_focus_session,
    get_active_focus_session,
    get_daily_summary,
    get_matrix_tasks,
    get_next_action_task,
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
    app.router.add_get("/app", app_page)
    app.router.add_get("/app/api/overview", api_overview)
    app.router.add_get("/matrix", matrix_page)
    app.router.add_get("/focus", focus_page)
    app.router.add_get("/matrix/api/tasks", api_tasks)
    app.router.add_post("/matrix/api/tasks", api_create_task)
    app.router.add_post("/matrix/api/tasks/{task_id}/matrix", api_update_matrix)
    app.router.add_post("/matrix/api/tasks/{task_id}/done", api_complete_task)
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


async def app_page(_request: web.Request) -> web.Response:
    return web.Response(text=APP_HTML, content_type="text/html")


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


async def api_overview(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    tasks = await get_matrix_tasks(user_id, limit=80)
    summary = await get_daily_summary(user_id)
    next_task = await get_next_action_task(user_id)
    active_focus = await get_active_focus_session(user_id)

    return web.json_response({
        "summary": summary,
        "next_task": task_payload(next_task) if next_task else None,
        "active_focus": focus_session_payload(active_focus),
        "tasks": [task_payload(task) for task in tasks],
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


def task_payload(task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "important": task.important,
        "urgent": task.urgent,
        "quadrant": task_quadrant(task.important, task.urgent),
    }


APP_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Noto Memento · Panel</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #f6f1e8;
      --ink: #171717;
      --muted: #706b62;
      --line: #ded6ca;
      --card: #fffdf8;
      --accent: #1f7a5a;
      --soft: #bddac7;
      --warm: #f1a37f;
      --blue: #8daee8;
      --drop: #c9bfae;
      --shadow: 0 12px 32px rgba(42, 33, 20, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(180deg, #fffaf1 0%, var(--bg) 48%, #ece3d5 100%);
      color: var(--ink);
      font: 15px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app { max-width: 980px; margin: 0 auto; padding: 16px; }
    h1 { margin: 0; font-size: 26px; letter-spacing: 0; }
    .muted { color: var(--muted); }
    .tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 14px 0; }
    .tab {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 9px 10px;
      background: rgba(255,255,255,.72);
      color: var(--ink);
      font: inherit;
      font-weight: 750;
    }
    .tab.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    .view { display: none; }
    .view.active { display: block; }
    .panel {
      background: rgba(255,253,248,.9);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      box-shadow: var(--shadow);
      margin-bottom: 10px;
    }
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .stat-value { display: block; font-size: 22px; font-weight: 900; line-height: 1; }
    .stat-label { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; }
    .composer { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    input, button { font: inherit; }
    .input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 11px 12px;
      outline: none;
    }
    .input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.12); }
    .primary {
      border: 0;
      border-radius: 7px;
      padding: 11px 14px;
      background: var(--accent);
      color: #fff;
      font-weight: 850;
    }
    .chips { display: flex; gap: 6px; overflow-x: auto; padding-top: 8px; }
    .chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--ink);
      padding: 7px 10px;
      white-space: nowrap;
    }
    .chip.active { border-color: var(--accent); background: #eef7f1; color: #14583f; font-weight: 750; }
    .task {
      width: 100%;
      border: 1px solid var(--line);
      border-left: 4px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 10px;
      margin-top: 7px;
      text-align: left;
    }
    .task[data-q="do"] { border-left-color: var(--warm); }
    .task[data-q="plan"] { border-left-color: var(--soft); }
    .task[data-q="delegate"] { border-left-color: var(--blue); }
    .task[data-q="drop"] { border-left-color: var(--drop); }
    .task.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.14); }
    .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; }
    .cell { min-height: 180px; }
    .cell-title { font-weight: 850; margin-bottom: 5px; }
    .focus-ring {
      width: min(70vw, 260px);
      aspect-ratio: 1;
      border-radius: 50%;
      display: grid;
      place-items: center;
      margin: 8px auto 12px;
      background: conic-gradient(var(--accent) var(--progress, 0deg), #e7dfd2 0);
      position: relative;
    }
    .focus-ring::after { content: ""; position: absolute; inset: 14px; border-radius: 50%; background: var(--card); }
    .focus-center { position: relative; z-index: 1; text-align: center; }
    .time { font-size: 46px; font-weight: 900; line-height: 1; }
    .controls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .ghost { border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--ink); padding: 11px; font-weight: 750; }
    .danger { background: var(--warm); }
    .hidden { display: none; }
    @media (max-width: 680px) {
      .app { padding: 14px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .composer { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="app">
    <h1>Панель</h1>
    <div class="muted">Мысли, задачи и фокус без лишнего шума.</div>

    <nav class="tabs">
      <button class="tab active" data-view="today">Сегодня</button>
      <button class="tab" data-view="matrix">Матрица</button>
      <button class="tab" data-view="focus">Фокус</button>
    </nav>

    <section class="view active" id="today">
      <div class="panel" id="nextPanel"></div>
      <div class="stats">
        <div class="panel"><span class="stat-value" id="statOpen">0</span><span class="stat-label">открыто</span></div>
        <div class="panel"><span class="stat-value" id="statDone">0</span><span class="stat-label">готово</span></div>
        <div class="panel"><span class="stat-value" id="statFocus">0</span><span class="stat-label">мин фокуса</span></div>
        <div class="panel"><span class="stat-value" id="statNotes">0</span><span class="stat-label">заметок</span></div>
      </div>
      <div class="panel" id="todayTasks"></div>
    </section>

    <section class="view" id="matrix">
      <div class="panel">
        <div class="composer">
          <input class="input" id="taskInput" maxlength="500" placeholder="Новая задача">
          <button class="primary" id="addTask">Добавить</button>
        </div>
        <div class="chips" id="quadrantChips">
          <button class="chip active" data-q="inbox">Входящие</button>
          <button class="chip" data-q="do">Сделать</button>
          <button class="chip" data-q="plan">План</button>
          <button class="chip" data-q="delegate">Делегировать</button>
          <button class="chip" data-q="drop">Убрать</button>
        </div>
      </div>
      <div class="grid" id="matrixGrid"></div>
      <div class="panel hidden" id="taskActions">
        <div id="selectedTitle" class="cell-title"></div>
        <div class="chips">
          <button class="chip" data-move="do">Сделать</button>
          <button class="chip" data-move="plan">План</button>
          <button class="chip" data-move="delegate">Делегировать</button>
          <button class="chip" data-move="drop">Убрать</button>
          <button class="chip" id="doneTask">Готово</button>
        </div>
      </div>
    </section>

    <section class="view" id="focus">
      <div class="panel">
        <div class="focus-ring" id="focusRing">
          <div class="focus-center">
            <div id="focusMethod" class="cell-title">Pomodoro</div>
            <div class="time" id="focusTime">25:00</div>
            <div class="muted" id="focusStatus">готов начать</div>
          </div>
        </div>
        <input class="input" id="focusInput" maxlength="120" placeholder="Над чем работаем">
        <div class="chips" id="focusMethods">
          <button class="chip active" data-method="Pomodoro" data-duration="25">25 мин</button>
          <button class="chip" data-method="Short Focus" data-duration="15">15 мин</button>
          <button class="chip" data-method="Deep Work" data-duration="60">60 мин</button>
        </div>
        <button class="primary" id="startFocus" style="width:100%; margin-top:10px;">Начать фокус</button>
        <div class="controls hidden" id="focusControls">
          <button class="ghost" id="finishFocus">Завершить</button>
          <button class="ghost danger" id="cancelFocus">Отменить</button>
        </div>
      </div>
    </section>
  </main>

  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    const labels = {
      do: ["Сделать", "важно и срочно"],
      plan: ["План", "важно"],
      delegate: ["Делегировать", "срочно"],
      drop: ["Убрать", "лишнее"],
      inbox: ["Входящие", "разобрать"]
    };
    const order = ["do", "plan", "delegate", "drop", "inbox"];
    let tasks = [];
    let selected = null;
    let newTaskQuadrant = "inbox";
    let focusSession = null;
    let focusTimer = null;
    let focusMethod = "Pomodoro";
    let focusDuration = 25;

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

    function taskButton(task) {
      const button = document.createElement("button");
      button.className = "task" + (selected?.id === task.id ? " selected" : "");
      button.dataset.q = task.quadrant;
      button.textContent = task.title;
      button.onclick = () => selectTask(task);
      return button;
    }

    function selectTask(task) {
      selected = task;
      document.getElementById("selectedTitle").textContent = task.title;
      document.getElementById("taskActions").classList.remove("hidden");
      renderMatrix();
    }

    function nextTask() {
      return tasks.find(task => task.quadrant === "do")
        || tasks.find(task => task.quadrant === "plan")
        || tasks.find(task => task.quadrant === "inbox")
        || null;
    }

    function renderToday(summary) {
      const next = nextTask();
      document.getElementById("nextPanel").innerHTML = next
        ? `<div class="muted">Следующий шаг</div><div class="cell-title">${escapeHtml(next.title)}</div>`
        : `<div class="cell-title">Пока нет задач</div><div class="muted">Добавь одну в матрице.</div>`;
      document.getElementById("statOpen").textContent = summary.open_tasks;
      document.getElementById("statDone").textContent = summary.done_tasks;
      document.getElementById("statFocus").textContent = summary.focus_minutes;
      document.getElementById("statNotes").textContent = summary.notes;
      const top = tasks.slice(0, 5);
      document.getElementById("todayTasks").innerHTML = `<div class="cell-title">Задачи</div>`;
      top.forEach(task => document.getElementById("todayTasks").appendChild(taskButton(task)));
    }

    function renderMatrix() {
      const grid = document.getElementById("matrixGrid");
      grid.innerHTML = "";
      order.forEach(quadrant => {
        const items = tasks.filter(task => task.quadrant === quadrant);
        const cell = document.createElement("section");
        cell.className = "panel cell";
        cell.innerHTML = `<div class="cell-title">${labels[quadrant][0]}</div><div class="muted">${labels[quadrant][1]} · ${items.length}</div>`;
        items.forEach(task => cell.appendChild(taskButton(task)));
        grid.appendChild(cell);
      });
    }

    function renderFocus() {
      const ring = document.getElementById("focusRing");
      const method = document.getElementById("focusMethod");
      const time = document.getElementById("focusTime");
      const status = document.getElementById("focusStatus");
      const controls = document.getElementById("focusControls");
      const start = document.getElementById("startFocus");

      if (!focusSession) {
        ring.style.setProperty("--progress", "0deg");
        method.textContent = focusMethod;
        time.textContent = format(focusDuration * 60);
        status.textContent = "готов начать";
        controls.classList.add("hidden");
        start.classList.remove("hidden");
        return;
      }

      const started = new Date(focusSession.started_at);
      const total = focusSession.duration_minutes * 60;
      const elapsed = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
      const left = Math.max(0, total - elapsed);
      const progress = Math.min(1, elapsed / total);
      ring.style.setProperty("--progress", `${Math.round(progress * 360)}deg`);
      method.textContent = focusSession.method;
      time.textContent = format(left);
      status.textContent = `${Math.round(progress * 100)}%`;
      controls.classList.remove("hidden");
      start.classList.add("hidden");
    }

    async function load() {
      const overview = await api("/app/api/overview");
      tasks = overview.tasks;
      focusSession = overview.active_focus;
      renderToday(overview.summary);
      renderMatrix();
      renderFocus();
      if (focusTimer) clearInterval(focusTimer);
      focusTimer = setInterval(renderFocus, 1000);
    }

    async function createTask() {
      const input = document.getElementById("taskInput");
      const title = input.value.trim();
      if (title.length < 2) return input.focus();
      await api("/matrix/api/tasks", {
        method: "POST",
        body: JSON.stringify({ title, quadrant: newTaskQuadrant === "inbox" ? null : newTaskQuadrant })
      });
      input.value = "";
      await load();
    }

    function escapeHtml(value) {
      return value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
    }

    document.querySelectorAll(".tab").forEach(tab => {
      tab.onclick = () => {
        document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
        document.querySelectorAll(".view").forEach(item => item.classList.remove("active"));
        tab.classList.add("active");
        document.getElementById(tab.dataset.view).classList.add("active");
      };
    });

    document.querySelectorAll("#quadrantChips .chip").forEach(chip => {
      chip.onclick = () => {
        newTaskQuadrant = chip.dataset.q;
        document.querySelectorAll("#quadrantChips .chip").forEach(item => item.classList.remove("active"));
        chip.classList.add("active");
      };
    });

    document.querySelectorAll("[data-move]").forEach(button => {
      button.onclick = async () => {
        if (!selected) return;
        await api(`/matrix/api/tasks/${selected.id}/matrix`, {
          method: "POST",
          body: JSON.stringify({ quadrant: button.dataset.move })
        });
        selected = null;
        document.getElementById("taskActions").classList.add("hidden");
        await load();
      };
    });

    document.getElementById("doneTask").onclick = async () => {
      if (!selected) return;
      await api(`/matrix/api/tasks/${selected.id}/done`, { method: "POST" });
      selected = null;
      document.getElementById("taskActions").classList.add("hidden");
      await load();
    };

    document.getElementById("addTask").onclick = createTask;
    document.getElementById("taskInput").addEventListener("keydown", event => {
      if (event.key === "Enter") createTask();
    });

    document.querySelectorAll("#focusMethods .chip").forEach(chip => {
      chip.onclick = () => {
        focusMethod = chip.dataset.method;
        focusDuration = Number(chip.dataset.duration);
        document.querySelectorAll("#focusMethods .chip").forEach(item => item.classList.remove("active"));
        chip.classList.add("active");
        renderFocus();
      };
    });

    document.getElementById("startFocus").onclick = async () => {
      const data = await api("/focus/api/start", {
        method: "POST",
        body: JSON.stringify({ method: focusMethod, duration_minutes: focusDuration })
      });
      focusSession = data.session;
      renderFocus();
    };

    document.getElementById("finishFocus").onclick = async () => {
      await api("/focus/api/finish", { method: "POST", body: "{}" });
      focusSession = null;
      await load();
    };

    document.getElementById("cancelFocus").onclick = async () => {
      await api("/focus/api/cancel", { method: "POST", body: "{}" });
      focusSession = null;
      renderFocus();
    };

    load();
  </script>
</body>
</html>
"""


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
      --bg: #f6f1e8;
      --ink: #171717;
      --muted: #6f6a60;
      --line: #ddd2c2;
      --card: #fffdf8;
      --surface: #fff9ef;
      --urgent: #f1a37f;
      --plan: #80bf9b;
      --delegate: #8daee8;
      --drop: #c9bfae;
      --accent: #1f7a5a;
      --shadow: 0 10px 30px rgba(42, 33, 20, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, #fffaf1 0%, var(--bg) 42%, #efe8dc 100%);
      color: var(--ink);
      font: 15px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app { padding: 18px; max-width: 1040px; margin: 0 auto; }
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
    header { display: flex; justify-content: space-between; gap: 14px; align-items: flex-end; margin-bottom: 14px; }
    h1 { margin: 0; font-size: 27px; letter-spacing: 0; }
    .hint { color: var(--muted); margin: 4px 0 0; }
    .composer {
      background: rgba(255, 253, 248, .9);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 12px;
      box-shadow: var(--shadow);
    }
    .input-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .task-input {
      width: 100%;
      min-height: 44px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 11px 12px;
      font: inherit;
      outline: none;
    }
    .task-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.12); }
    .add-button {
      border: 0;
      border-radius: 7px;
      padding: 0 16px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }
    .chips { display: flex; gap: 6px; overflow-x: auto; padding-top: 8px; }
    .chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--ink);
      padding: 7px 10px;
      font: inherit;
      white-space: nowrap;
      cursor: pointer;
    }
    .chip.active { border-color: var(--accent); background: #eef7f1; color: #14583f; font-weight: 750; }
    .workspace-controls {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      margin-bottom: 12px;
    }
    .search-input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: rgba(255,255,255,.86);
      color: var(--ink);
      padding: 10px 11px;
      font: inherit;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.12); }
    .filter-row { display: flex; gap: 6px; overflow-x: auto; }
    .next-card {
      display: none;
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: rgba(255,253,248,.86);
      padding: 11px 12px;
      margin-bottom: 12px;
      box-shadow: var(--shadow);
    }
    .next-card.visible { display: block; }
    .next-label { color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; letter-spacing: .04em; }
    .next-title { margin-top: 4px; font-weight: 850; }
    .toolbar {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .summary-item {
      background: rgba(255, 253, 248, .78);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
    }
    .summary-value { display: block; font-size: 20px; font-weight: 850; line-height: 1; }
    .summary-label { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .matrix-shell {
      position: relative;
      padding: 28px 0 0 30px;
    }
    .axis {
      position: absolute;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .axis-top { top: 6px; left: 50%; transform: translateX(-50%); }
    .axis-left { left: 0; top: 50%; transform: translateY(-50%) rotate(-90deg); transform-origin: center; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .cell {
      min-height: 235px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
    }
    .cell[data-q="do"] { border-top: 5px solid var(--urgent); }
    .cell[data-q="plan"] { border-top: 5px solid var(--plan); }
    .cell[data-q="delegate"] { border-top: 5px solid var(--delegate); }
    .cell[data-q="drop"] { border-top: 5px solid var(--drop); }
    .cell-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; margin-bottom: 8px; }
    .cell-title { font-weight: 850; font-size: 16px; }
    .count { color: var(--muted); font-size: 13px; }
    .task {
      width: 100%;
      display: block;
      border: 1px solid var(--line);
      border-left: 4px solid transparent;
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      padding: 10px 10px;
      margin: 7px 0;
      text-align: left;
      font: inherit;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(23,23,23,.04);
    }
    .task[data-q="do"] { border-left-color: var(--urgent); }
    .task[data-q="plan"] { border-left-color: var(--plan); }
    .task[data-q="delegate"] { border-left-color: var(--delegate); }
    .task[data-q="drop"] { border-left-color: var(--drop); }
    .task[data-q="inbox"] { border-left-color: var(--line); }
    .task:hover { border-color: #bba98f; }
    .task:active { transform: translateY(1px); }
    .task.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.16); }
    .inbox {
      margin-top: 14px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 12px;
      background: rgba(255,255,255,.58);
    }
    .actions {
      display: none;
      position: sticky;
      bottom: 0;
      margin: 14px -18px -18px;
      padding: 12px 18px 18px;
      background: rgba(246,241,232,.97);
      border-top: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }
    .actions.visible { display: block; }
    .actions-title { font-weight: 800; margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .action {
      border: 0;
      border-radius: 7px;
      padding: 11px 10px;
      font: inherit;
      font-weight: 700;
      color: var(--ink);
      cursor: pointer;
    }
    .action[data-q="do"] { background: var(--urgent); }
    .action[data-q="plan"] { background: var(--plan); }
    .action[data-q="delegate"] { background: var(--delegate); }
    .action[data-q="drop"] { background: var(--drop); }
    .done-action { width: 100%; margin-top: 8px; background: var(--accent); color: #fff; }
    .empty { color: var(--muted); padding: 10px 0; }
    @media (max-width: 640px) {
      .app { padding: 14px; }
      header { display: block; }
      h1 { font-size: 22px; }
      .input-row { grid-template-columns: 1fr; }
      .add-button { min-height: 42px; }
      .workspace-controls { grid-template-columns: 1fr; }
      .toolbar { grid-template-columns: repeat(5, minmax(54px, 1fr)); overflow-x: auto; padding-bottom: 2px; }
      .summary-item { min-width: 68px; padding: 8px; }
      .summary-value { font-size: 18px; }
      .matrix-shell { padding-left: 0; padding-top: 22px; }
      .axis-left { display: none; }
      .grid { gap: 8px; }
      .cell { min-height: 190px; padding: 10px; }
      .cell-title { font-size: 14px; }
      .task { font-size: 14px; padding: 8px; }
      .actions { margin-left: -14px; margin-right: -14px; margin-bottom: -14px; padding-left: 14px; padding-right: 14px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <nav class="nav">
      <a class="active" href="/matrix?v=3.7">Матрица</a>
      <a href="/focus?v=3.7">Фокус</a>
    </nav>

    <header>
      <div>
        <h1>Матрица</h1>
        <p class="hint">Пиши задачи здесь. Потом раскидывай по важности и срочности.</p>
      </div>
    </header>

    <section class="composer">
      <div class="input-row">
        <input class="task-input" id="taskInput" maxlength="500" placeholder="Новая задача">
        <button class="add-button" id="addTask">Добавить</button>
      </div>
      <div class="chips" id="quadrantChips">
        <button class="chip active" data-q="inbox">Входящие</button>
        <button class="chip" data-q="do">Сделать</button>
        <button class="chip" data-q="plan">План</button>
        <button class="chip" data-q="delegate">Делегировать</button>
        <button class="chip" data-q="drop">Убрать</button>
      </div>
    </section>

    <section class="workspace-controls">
      <input class="search-input" id="taskSearch" placeholder="Найти задачу">
      <div class="filter-row" id="viewFilters">
        <button class="chip active" data-filter="all">Все</button>
        <button class="chip" data-filter="inbox">Входящие</button>
        <button class="chip" data-filter="do">Сделать</button>
        <button class="chip" data-filter="plan">План</button>
        <button class="chip" data-filter="delegate">Делегировать</button>
        <button class="chip" data-filter="drop">Убрать</button>
      </div>
    </section>

    <section class="next-card" id="nextCard">
      <div class="next-label">Следующий шаг</div>
      <div class="next-title" id="nextTitle"></div>
    </section>

    <section class="toolbar" id="summary"></section>
    <section class="matrix-shell">
      <div class="axis axis-top">Срочно</div>
      <div class="axis axis-left">Важно</div>
      <section class="grid" id="grid"></section>
    </section>
    <section class="inbox" id="inbox"></section>

    <section class="actions" id="actions">
      <div class="actions-title" id="selectedTitle"></div>
      <div class="action-grid">
        <button class="action" data-q="do">Сделать</button>
        <button class="action" data-q="plan">План</button>
        <button class="action" data-q="delegate">Делегировать</button>
        <button class="action" data-q="drop">Убрать</button>
      </div>
      <button class="action done-action" id="completeTask">Готово</button>
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
    let newTaskQuadrant = "inbox";
    let viewFilter = "all";
    let searchQuery = "";

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
      button.dataset.q = task.quadrant;
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

    function resetSelection() {
      selected = null;
      document.getElementById("actions").classList.remove("visible");
    }

    function renderCell(quadrant) {
      const items = visibleTasks().filter(task => task.quadrant === quadrant);
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

    function visibleTasks() {
      return tasks.filter(task => {
        const byFilter = viewFilter === "all" || task.quadrant === viewFilter;
        const bySearch = !searchQuery || task.title.toLowerCase().includes(searchQuery);
        return byFilter && bySearch;
      });
    }

    function nextTask() {
      return tasks.find(task => task.quadrant === "do")
        || tasks.find(task => task.quadrant === "plan")
        || tasks.find(task => task.quadrant === "inbox")
        || tasks[0]
        || null;
    }

    function render() {
      const grid = document.getElementById("grid");
      grid.innerHTML = "";
      order.forEach(quadrant => grid.appendChild(renderCell(quadrant)));

      const summary = document.getElementById("summary");
      const values = [
        ["Всего", tasks.length],
        [labels.do[0], tasks.filter(task => task.quadrant === "do").length],
        [labels.plan[0], tasks.filter(task => task.quadrant === "plan").length],
        [labels.delegate[0], tasks.filter(task => task.quadrant === "delegate").length],
        ["Без кв.", tasks.filter(task => task.quadrant === "inbox").length],
      ];
      summary.innerHTML = values.map(([label, value]) => `
        <div class="summary-item">
          <span class="summary-value">${value}</span>
          <span class="summary-label">${label}</span>
        </div>
      `).join("");

      const inboxItems = visibleTasks().filter(task => task.quadrant === "inbox");
      const inbox = document.getElementById("inbox");
      inbox.innerHTML = `<div class="cell-head"><div><div class="cell-title">Без квадранта</div><div class="count">разбери позже или сейчас</div></div><div class="count">${inboxItems.length}</div></div>`;
      if (!inboxItems.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Все задачи разнесены";
        inbox.appendChild(empty);
      }
      inboxItems.forEach(task => inbox.appendChild(taskButton(task)));

      const next = nextTask();
      const nextCard = document.getElementById("nextCard");
      if (next) {
        document.getElementById("nextTitle").textContent = next.title;
        nextCard.classList.add("visible");
        nextCard.onclick = () => selectTask(next);
      } else {
        nextCard.classList.remove("visible");
        nextCard.onclick = null;
      }
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

    async function createTask() {
      const input = document.getElementById("taskInput");
      const title = input.value.trim();
      if (title.length < 2) {
        input.focus();
        return;
      }

      await api("/matrix/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          title,
          quadrant: newTaskQuadrant === "inbox" ? null : newTaskQuadrant
        })
      });

      input.value = "";
      resetSelection();
      await load();
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
        resetSelection();
        render();
      };
    });

    document.getElementById("completeTask").onclick = async () => {
      if (!selected) return;
      await api(`/matrix/api/tasks/${selected.id}/done`, { method: "POST" });
      tasks = tasks.filter(task => task.id !== selected.id);
      resetSelection();
      render();
    };

    document.getElementById("addTask").onclick = createTask;
    document.getElementById("taskInput").addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        createTask();
      }
    });

    document.querySelectorAll(".chip").forEach(button => {
      button.onclick = () => {
        if (!button.dataset.q) return;
        newTaskQuadrant = button.dataset.q;
        document.querySelectorAll("#quadrantChips .chip").forEach(item => item.classList.remove("active"));
        button.classList.add("active");
      };
    });

    document.querySelectorAll("#viewFilters .chip").forEach(button => {
      button.onclick = () => {
        viewFilter = button.dataset.filter;
        document.querySelectorAll("#viewFilters .chip").forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        render();
      };
    });

    document.getElementById("taskSearch").addEventListener("input", event => {
      searchQuery = event.target.value.trim().toLowerCase();
      render();
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
      <a href="/matrix?v=3.7">Матрица</a>
      <a class="active" href="/focus?v=3.7">Фокус</a>
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
