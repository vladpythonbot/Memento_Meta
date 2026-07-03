from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from config import WEBAPP_URL


BTN_APP = "🧭 Панель"
APP_VERSION = "6"


def app_url(webapp_url: str | None = None) -> str | None:
    base_url = (webapp_url or WEBAPP_URL or "").strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/app?v={APP_VERSION}"


def panel_button() -> KeyboardButton:
    return KeyboardButton(text=BTN_APP)


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[panel_button()]],
    resize_keyboard=True,
    one_time_keyboard=False,
    is_persistent=True,
)


def app_links_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup | None:
    url = app_url(webapp_url)
    if not url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть панель", web_app=WebAppInfo(url=url))],
        ]
    )
