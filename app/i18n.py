"""
Internationalization — static JSON translation catalogs.

Loaded once at startup. Available in Jinja2 templates via `t()` helper.
Relationship terms loaded separately for domain-specific cultural accuracy.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_translations: dict[str, dict] = {}
_relationship_terms: dict[str, dict] = {}

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "es", "ru")

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locales")


def load_translations() -> None:
    """Load all locale JSON files from disk. Called once at startup."""
    global _translations, _relationship_terms

    for locale in SUPPORTED_LOCALES:
        # UI strings
        ui_path = os.path.join(_LOCALES_DIR, f"{locale}.json")
        if os.path.exists(ui_path):
            with open(ui_path, encoding="utf-8") as f:
                _translations[locale] = json.load(f)
            logger.info("Loaded locale: %s (%d keys)", locale, _count_keys(_translations[locale]))

        # Relationship terms
        rel_path = os.path.join(_LOCALES_DIR, "relationships", f"{locale}.json")
        if os.path.exists(rel_path):
            with open(rel_path, encoding="utf-8") as f:
                _relationship_terms[locale] = json.load(f)


def get_translations(locale: str = DEFAULT_LOCALE) -> dict:
    """Get UI translation dict for a locale, falling back to English."""
    return _translations.get(locale, _translations.get(DEFAULT_LOCALE, {}))


def get_relationship_terms(locale: str = DEFAULT_LOCALE) -> dict:
    """Get relationship term dict for a locale."""
    return _relationship_terms.get(locale, _relationship_terms.get(DEFAULT_LOCALE, {}))


def t(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Translate a dotted key (e.g. 'nav.tree') for a locale.

    Falls back to English, then to the key itself.
    """
    translations = get_translations(locale)
    return _resolve_dotted(translations, key) or _resolve_dotted(
        _translations.get(DEFAULT_LOCALE, {}), key
    ) or key


def rel_term(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Get a relationship term by key."""
    terms = get_relationship_terms(locale)
    return terms.get(key, get_relationship_terms(DEFAULT_LOCALE).get(key, key))


def _resolve_dotted(d: dict, key: str) -> str | None:
    """Resolve 'nav.tree' → d['nav']['tree']."""
    parts = key.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current if isinstance(current, str) else None


def _count_keys(d: dict, prefix: str = "") -> int:
    count = 0
    for k, v in d.items():
        if isinstance(v, dict):
            count += _count_keys(v, f"{prefix}{k}.")
        else:
            count += 1
    return count
