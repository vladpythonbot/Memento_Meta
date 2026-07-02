# Memento Meta

Memento Meta is a minimalist Telegram bot and Telegram Web App for quick task capture and Eisenhower matrix sorting.

## Concept

The bot works like a lightweight inbox: send any text to Telegram, and it becomes an open task. The Web App is the workspace for sorting tasks into a 2x2 matrix, marking tasks done, and deleting noise.

The product deliberately avoids heavy task-manager mechanics and overloaded menus. The core flow is:

```text
text message -> inbox -> matrix -> done/delete
```

## Naming

Display name: `Memento Meta`

Telegram username: `memento_meta_bot`

## Scope

- Free-text task capture in Telegram.
- Multi-line messages become multiple tasks.
- Persistent one-button bot panel.
- Telegram Web App task workspace.
- Inbox area for unsorted tasks.
- Eisenhower 2x2 matrix.
- Drag-and-drop between inbox and quadrants.
- Task completion and deletion.
- Daily and weekly task summaries.
- Russian interface.
- English code and database fields.

## Bot UI

- `🧭 Панель`

Everything else is intentionally handled by plain text or slash commands.

## Web App

The panel runs at `/app` and `/matrix`.

Set this variable in Railway:

```bash
WEBAPP_URL=https://your-railway-domain.up.railway.app
```

The bot process also starts an HTTP server on `PORT`, so Railway should run it as a `web` process.

## Run Locally

1. Create `.env` from `.env.example`.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the bot:

```bash
python main.py
```

## Railway

Set `BOT_TOKEN` and `WEBAPP_URL` in Railway variables.

For SQLite persistence, attach a Railway Volume and set:

```bash
DB_PATH=/data/memento_meta.db
```
