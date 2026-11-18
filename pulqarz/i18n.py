"""Texts for the bot, read from shared/locales/*.json (the Mini App and the browser demo read the same files)."""

from __future__ import annotations

import html
import json
import re
from functools import cache
from pathlib import Path

from .core.money import format_number

LANGS = ("uz", "ru")
DEFAULT_LANG = "uz"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "shared" / "locales"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class Raw(str):
    """A parameter that is already safe HTML (for example a nested, already-rendered text)."""


@cache
def catalog(lang: str) -> dict[str, str]:
    with open(LOCALE_DIR / f"{lang}.json", encoding="utf-8") as fh:
        return json.load(fh)


def norm_lang(lang: str | None) -> str:
    if lang and lang[:2].lower() == "ru":
        return "ru"
    return DEFAULT_LANG


def render(template: str, params: dict) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) not in params:
            return m.group(0)
        value = params[m.group(1)]
        return value if isinstance(value, Raw) else html.escape(str(value), quote=False)

    return _PLACEHOLDER.sub(sub, template)


def t(lang: str, key: str, **params: object) -> str:
    """Localized text; parameters are HTML-escaped unless wrapped in ``Raw``."""
    lang = norm_lang(lang)
    template = catalog(lang).get(key) or catalog(DEFAULT_LANG).get(key) or key
    return render(template, params)


def money(lang: str, minor: int, cur: str) -> str:
    return render(catalog(norm_lang(lang))[f"amount.{cur}"], {"n": format_number(minor)})


def day(iso: str) -> str:
    """``2026-12-25`` -> ``25.12.2026``."""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"
