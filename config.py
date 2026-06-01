import os

from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
DB_PATH = os.getenv("DB_PATH", "noto_memento.db")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Europe/Kyiv")
