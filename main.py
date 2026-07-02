import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.types import MenuButtonWebApp, WebAppInfo

from config import PORT, WEBAPP_URL
from bot import bot, dp
from db import init_db
from routers import router
from webapp import start_webapp
from keyboards import app_url


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def configure_menu_button() -> None:
    url = app_url(WEBAPP_URL)
    if not url:
        logger.warning("WEBAPP_URL is empty; Telegram menu button was not configured")
        return

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Панель",
                web_app=WebAppInfo(url=url),
            )
        )
        logger.info("Telegram menu button configured: %s", url)
    except TelegramBadRequest as exc:
        logger.error("Failed to configure Telegram menu button: %s", exc)


async def main():
    try:
        me = await bot.get_me()
        logger.info("Bot authorized: @%s", me.username)
        await init_db()
        logger.info("Database initialized")
        web_runner = await start_webapp()
        logger.info("Web app started on port %s", PORT)
        await configure_menu_button()

        dp.include_router(router)
        logger.info("Memento Meta started")
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error("Telegram rejected BOT_TOKEN. Check .env or Railway variables.")
    finally:
        if "web_runner" in locals():
            await web_runner.cleanup()
        await bot.session.close()
        logger.info("Memento Meta stopped")


if __name__ == "__main__":
    asyncio.run(main())
