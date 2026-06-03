# Noto Memento

Noto Memento is a minimalist Telegram bot for notes, daily tasks, and focus sessions.

## Concept

Noto Memento helps the user quickly unload thoughts, turn them into tasks, choose a focus method, and see a simple daily summary.

The product idea is not to copy a heavy task manager inside Telegram. Noto Memento should feel calm, fast, and useful in ordinary daily work.

## Naming

Display name: `Noto Memento`

Telegram username: `memento_meta_bot`

## MVP Scope

- Quick notes.
- Saved Messages-style text capture.
- Web App task capture.
- Today tasks.
- Task completion.
- Eisenhower matrix for task prioritization.
- Managed focus sessions.
- Daily summary.
- Russian interface.
- English code and database fields.

## First Screen

- `🧭 Панель`
- `📝 Записать`

## Focus Methods

- Pomodoro: 25 minutes.
- Short Focus: 15 minutes.
- Deep Work: 90 minutes.

## Time Management Methods

- Eisenhower matrix: important/urgent task sorting.
- Telegram Web App matrix: visual 2x2 task board with quick task capture.

## Version 2 Direction

- Eisenhower matrix as a first-class screen.
- Focus session status.
- Animated focus progress message.
- Manual focus finish/cancel actions.
- Protection from running several focus sessions at the same time.
- Saved notes screen.
- Deleting saved notes.
- Weekly review with a suggested next step.

## Telegram Web App

The v4 panel runs as a Telegram Web App at `/app`. The bot stays minimal, while the Web App becomes the main workspace with three modes: Today, Matrix, and Focus.

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
DB_PATH=/data/noto_memento.db
```
