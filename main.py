import asyncio
import logging

from aiogram.exceptions import TelegramUnauthorizedError

from bot import bot, dp
from db import init_db
from routers import router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    try:
        me = await bot.get_me()
        logger.info("Bot authorized: @%s", me.username)
        await init_db()
        logger.info("Database initialized")

        dp.include_router(router)
        logger.info("Noto Memento started")
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error("Telegram rejected BOT_TOKEN. Check .env or Railway variables.")
    finally:
        await bot.session.close()
        logger.info("Noto Memento stopped")


if __name__ == "__main__":
    asyncio.run(main())
