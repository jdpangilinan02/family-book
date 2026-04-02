import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from app.config import get_settings


DEFAULT_ACCENT = "forest"
ACCENT_PRESETS = {"forest", "ocean", "rose"}


@dataclass
class SiteSettings:
    title: Optional[str] = None
    accent: str = DEFAULT_ACCENT


_cache: SiteSettings | None = None


def _settings_path() -> Path:
    settings = get_settings()
    path = Path(settings.DATA_DIR) / "site.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_site_settings(force_reload: bool = False) -> SiteSettings:
    global _cache
    if _cache and not force_reload:
        return _cache

    path = _settings_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            title = data.get("title") or None
            accent = data.get("accent") or DEFAULT_ACCENT
            if accent not in ACCENT_PRESETS:
                accent = DEFAULT_ACCENT
            _cache = SiteSettings(title=title, accent=accent)
            return _cache
        except Exception:
            # fall through to defaults
            pass

    _cache = SiteSettings()
    return _cache


def save_site_settings(title: Optional[str], accent: str | None = None) -> SiteSettings:
    clean_title = (title or "").strip() or None
    clean_accent = accent if accent in ACCENT_PRESETS else DEFAULT_ACCENT

    settings = SiteSettings(title=clean_title, accent=clean_accent)
    path = _settings_path()
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")

    global _cache
    _cache = settings
    return settings
