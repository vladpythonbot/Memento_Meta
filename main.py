import asyncio
import logging

from aiogram.exceptions import TelegramUnauthorizedError

from config import PORT
from bot import bot, dp
from db import init_db
from routers import router
from webapp import start_webapp


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
        web_runner = await start_webapp()
        logger.info("Web app started on port %s", PORT)

        dp.include_router(router)
        logger.info("Noto Memento started")
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error("Telegram rejected BOT_TOKEN. Check .env or Railway variables.")
    finally:
        if "web_runner" in locals():
            await web_runner.cleanup()
        await bot.session.close()
        logger.info("Noto Memento stopped")


if __name__ == "__main__":
    asyncio.run(main())
