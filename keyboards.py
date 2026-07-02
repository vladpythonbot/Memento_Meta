from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo


BTN_APP = "🧭 Панель"


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_APP)]],
    resize_keyboard=True,
    one_time_keyboard=False,
    is_persistent=True,
)


def app_links_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup | None:
    if not webapp_url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть панель", web_app=WebAppInfo(url=f"{webapp_url}/app?v=6"))],
        ]
    )
