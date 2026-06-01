from aiogram import Bot, Dispatcher

from config import BOT_TOKEN


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Set it in .env or Railway variables.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

