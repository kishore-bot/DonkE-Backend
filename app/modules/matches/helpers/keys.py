from app.core.platform import Platform


def pending_analysis_key(platform: Platform) -> str:
    return f"{platform.settings.redis_prefix}:ai:analysis:pending"
