from app.modules.ai.helpers.prompts import LANGUAGE_NAMES, PROMPTS, accepted
from app.modules.ai.schemas.source import Source
from app.modules.ai.services.gateway import Gateway
from app.modules.identity.schemas.profile import Language


async def reword(
    gateway: Gateway,
    prompt_id: str,
    fact: str,
    language: Language,
    *,
    words: int = 40,
    keep: tuple[str, ...] = (),
    **values: str,
) -> tuple[str, Source]:
    """Return Gemini's rewording of `fact` if it passes validation, else `fact`."""
    prompt = PROMPTS[prompt_id]
    redis = gateway.platform.redis
    usage = gateway.usage_key()
    if gateway.provider is None:
        await redis.hincrby(usage, f"{prompt_id}_template", 1)
        return fact, "template"
    text = prompt.text.format(
        language=LANGUAGE_NAMES[language], words=words, fact=fact, **values
    )
    written = await gateway.call(
        prompt_id, lambda provider: provider.write(prompt_id, text)
    )
    await redis.hincrby(usage, f"prompt:{prompt.label}", 1)
    candidate = written.text.strip().strip('"') if written else ""
    if written and accepted(candidate, fact, language, words, keep):
        await redis.hincrby(usage, f"{prompt_id}_ai", 1)
        return candidate, "gemini"
    if written:
        await redis.hincrby(usage, f"{prompt_id}_invalid", 1)
    await redis.hincrby(usage, f"{prompt_id}_template", 1)
    return fact, "template"
