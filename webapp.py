import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN, HOST, PORT
from db import (
    add_task,
    clear_task_matrix,
    complete_task,
    delete_task,
    get_daily_summary,
    get_matrix_tasks,
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
    app.router.add_get("/matrix", app_page)
    app.router.add_get("/matrix/api/tasks", api_tasks)
    app.router.add_post("/matrix/api/tasks", api_create_task)
    app.router.add_post("/matrix/api/tasks/{task_id}/matrix", api_update_matrix)
    app.router.add_post("/matrix/api/tasks/{task_id}/done", api_complete_task)
    app.router.add_delete("/matrix/api/tasks/{task_id}", api_delete_task)
    app.router.add_get("/app/api/summary", api_summary)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    return runner


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "memento-meta"})


async def app_page(_request: web.Request) -> web.Response:
    return web.Response(text=APP_HTML, content_type="text/html")


async def api_tasks(request: web.Request) -> web.Response:
    user_id = user_id_from_request(request)
    tasks = await get_matrix_tasks(user_id, limit=100)
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


APP_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memento Meta</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #f7f3ea;
      --ink: #171717;
      --muted: #6d665d;
      --line: #ded2c2;
      --card: #fffdf8;
      --accent: #1f7a5a;
      --urgent: #ef9d77;
      --plan: #77b98f;
      --delegate: #8aa9de;
      --drop: #bfb4a4;
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
    .app { max-width: 1180px; margin: 0 auto; padding: 14px; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-end; margin-bottom: 12px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .hint { color: var(--muted); margin: 4px 0 0; }
    .composer, .panel, .cell, .metric {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .composer { padding: 10px; margin-bottom: 10px; }
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
    .summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }
    .metric { padding: 9px; box-shadow: none; }
    .metric b { display: block; font-size: 21px; line-height: 1; }
    .metric span { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .workspace { display: grid; grid-template-columns: minmax(250px, .85fr) minmax(0, 1.5fr); gap: 12px; }
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
      cursor: grab;
      touch-action: none;
      user-select: none;
    }
    .task:active { cursor: grabbing; }
    .task[data-q="do"] { border-left-color: var(--urgent); }
    .task[data-q="plan"] { border-left-color: var(--plan); }
    .task[data-q="delegate"] { border-left-color: var(--delegate); }
    .task[data-q="drop"] { border-left-color: var(--drop); }
    .task.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(31,122,90,.14); }
    .task.dragging { opacity: .35; }
    .task-ghost {
      position: fixed;
      z-index: 80;
      width: min(300px, calc(100vw - 28px));
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
    .matrix { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .cell { min-height: 235px; padding: 11px; }
    .cell[data-q="do"] { border-top: 5px solid var(--urgent); }
    .cell[data-q="plan"] { border-top: 5px solid var(--plan); }
    .cell[data-q="delegate"] { border-top: 5px solid var(--delegate); }
    .cell[data-q="drop"] { border-top: 5px solid var(--drop); }
    .cell.drop-target, .panel.drop-target { background: #f4fff6; border-color: rgba(31,122,90,.55); }
    .cell-head { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
    .cell-title { font-weight: 900; }
    .count { color: var(--muted); font-size: 13px; }
    .empty { color: var(--muted); padding: 10px 0; }
    @media (max-width: 760px) {
      .app { padding: 10px; }
      header { display: block; }
      h1 { font-size: 22px; }
      .input-row, .workspace { grid-template-columns: 1fr; }
      .summary { grid-template-columns: repeat(3, minmax(74px, 1fr)); }
      .matrix { grid-template-columns: repeat(2, minmax(145px, 1fr)); overflow-x: auto; }
      .cell { min-height: 180px; padding: 9px; }
      .task { padding: 9px; font-size: 14px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header>
      <div>
        <h1>Memento Meta</h1>
        <p class="hint">Быстрый входящие → матрица → готово.</p>
      </div>
    </header>

    <section class="composer">
      <div class="input-row">
        <input id="taskInput" maxlength="500" placeholder="Новая задача">
        <button class="primary" id="addTask">Добавить</button>
      </div>
    </section>

    <section class="summary" id="summary"></section>

    <section class="workspace">
      <section class="panel" id="incomingPanel">
        <div class="panel-title">Входящие</div>
        <div class="muted">Новые задачи. Перетащи в матрицу или оставь на потом.</div>
        <div class="list" id="incomingList"></div>
      </section>
      <section class="matrix" id="matrixGrid"></section>
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
      document.getElementById("summary").innerHTML = [
        ["Входящие", inbox],
        ["Открыто", tasks.length],
        ["Готово сегодня", summary.done_tasks || 0],
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
      await load();
    }

    async function deleteTask(task) {
      await api(`/matrix/api/tasks/${task.id}`, { method: "DELETE" });
      tasks = tasks.filter(item => item.id !== task.id);
      selected = null;
      await load();
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
