"""i18n id/en — middleware + catalog + helper terjemahan untuk Jinja & route."""
from contextvars import ContextVar
from collections.abc import Callable

from fastapi import Request

COOKIE_NAME = "rani_lang"
SUPPORTED = ("id", "en")
DEFAULT_LANG = "id"
LANG_LABELS = {"id": "Bahasa Indonesia", "en": "English"}

_current_lang: ContextVar[str] = ContextVar("rani_lang", default=DEFAULT_LANG)
_current_path: ContextVar[str] = ContextVar("rani_path", default="/")


def cookie_lang(request: Request) -> str:
    lang = (request.cookies.get(COOKIE_NAME) or DEFAULT_LANG).lower()
    return lang if lang in SUPPORTED else DEFAULT_LANG


def current_lang() -> str:
    return _current_lang.get()


def current_path() -> str:
    return _current_path.get()


def set_lang(lang: str, path: str = "/"):
    if lang not in SUPPORTED:
        lang = DEFAULT_LANG
    return _current_lang.set(lang), _current_path.set(path)


def reset_lang(token) -> None:
    lang_token, path_token = token
    _current_lang.reset(lang_token)
    _current_path.reset(path_token)


def translate(key: str, lang: str | None = None, **kwargs) -> str:
    from app.i18n_strings import CATALOG

    lang = lang or current_lang()
    entry = CATALOG.get(lang, {}).get(key)
    if entry is None:
        entry = CATALOG.get(DEFAULT_LANG, {}).get(key, key)
    if kwargs:
        try:
            return entry.format(**kwargs)
        except (KeyError, IndexError):
            return entry
    return entry


def t(key: str, **kwargs) -> str:
    """Jinja global: {{ t('nav.dashboard') }}"""
    return translate(key, **kwargs)


def request_t(request: Request, key: str, **kwargs) -> str:
    """Terjemah untuk route handler (tanpa contextvar di luar request)."""
    lang = getattr(request.state, "lang", None) or cookie_lang(request)
    return translate(key, lang, **kwargs)
