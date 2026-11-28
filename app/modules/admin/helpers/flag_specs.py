from typing import Any

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.admin.dto.flag_spec import FlagSpec

FLAGS: dict[str, FlagSpec] = {
    "ai_enabled": FlagSpec(bool, "Master switch for every Gemini feature"),
    "commentary_enabled": FlagSpec(bool, "Live commentary lines and voice"),
    "ai_text_daily_calls": FlagSpec(int, "Daily Gemini text call budget", 0, 5000),
    "ai_voice_daily_calls": FlagSpec(int, "Daily Gemini voice call budget", 0, 5000),
    "maintenance_notice": FlagSpec(str, "Banner shown in the app (empty hides it)"),
}


def defaults(platform: Platform) -> dict[str, Any]:
    settings = platform.settings
    return {
        "ai_enabled": True,
        "commentary_enabled": True,
        "ai_text_daily_calls": settings.ai_text_daily_calls,
        "ai_voice_daily_calls": settings.ai_voice_daily_calls,
        "maintenance_notice": "",
    }


def validate(key: str, value: Any) -> Any:
    spec = FLAGS.get(key)
    if spec is None:
        raise AppError(404, "flag_not_found", "Unknown runtime flag")
    if spec.kind is bool and isinstance(value, bool):
        return value
    if (
        spec.kind is int
        and isinstance(value, int)
        and not isinstance(value, bool)
        and spec.minimum <= value <= spec.maximum
    ):
        return value
    if spec.kind is str and isinstance(value, str) and len(value) <= 200:
        return value.strip()
    raise AppError(
        422, "invalid_flag_value", f"{key} needs a valid {spec.kind.__name__}"
    )
