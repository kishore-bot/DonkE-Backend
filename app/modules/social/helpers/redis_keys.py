from app.core.platform import Platform


def key(platform: Platform, *parts: object) -> str:
    return ":".join([platform.settings.redis_prefix, "social", *map(str, parts)])


def text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value
