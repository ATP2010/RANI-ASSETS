"""Template engine + global template variables."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.version import VERSION

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["version"] = VERSION


def fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(value)


for name, fn in {"fmt_dt": fmt_dt}.items():
    templates.env.filters[name] = fn