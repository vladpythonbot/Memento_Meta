from config import WEBAPP_URL


APP_VERSION = "6"


def app_url(webapp_url: str | None = None) -> str | None:
    base_url = (webapp_url or WEBAPP_URL or "").strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/app?v={APP_VERSION}"
