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
- Today tasks.
- Task completion.
- Eisenhower matrix for task prioritization.
- Managed focus sessions.
- Daily summary.
- Russian interface.
- English code and database fields.

## First Screen

- `📝 Записать`
- `📅 Сегодня`
- `🎯 Фокус`
- `📊 Итог`

## Focus Methods

- Pomodoro: 25 minutes.
- Short Focus: 15 minutes.
- Deep Work: 90 minutes.

## Time Management Methods

- Eisenhower matrix: important/urgent task sorting.

## Version 2 Direction

- Eisenhower matrix as a first-class screen.
- Focus session status.
- Animated focus progress message.
- Manual focus finish/cancel actions.
- Protection from running several focus sessions at the same time.

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

Set `BOT_TOKEN` in Railway variables. `DB_PATH` can be left as default for local SQLite storage, but for long-term production use a persistent database is recommended.
