"""Template engine + global template variables."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.version import VERSION

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["version"] = VERSION


DISPLAY_TZ = ZoneInfo("Asia/Jakarta")  # semua waktu di UI = WIB


def fmt_dt(value) -> str:
    """Format waktu untuk UI dalam Asia/Jakarta (datetime naive dianggap sudah lokal)."""
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    try:
        if hasattr(value, "astimezone") and value.tzinfo is not None:
            value = value.astimezone(DISPLAY_TZ)
        return value.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(value)


for name, fn in {"fmt_dt": fmt_dt}.items():
    templates.env.filters[name] = fn