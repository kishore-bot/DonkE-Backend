"""AI backends behind `AIProvider`, chosen by configuration.

Features depend on the `Gateway`, which holds an `AIProvider`; none of them
names a vendor. `DONKE_AI_PROVIDER` picks the backend. To add one, implement
`AIProvider` (including `models` and `close`) and call
`register_provider("name", factory)` before the gateway opens. A factory
returns None when the backend is not configured, which turns AI features off.
"""

from collections.abc import Callable

from app.core.config import Settings
from app.modules.ai.provider import AIProvider

ProviderFactory = Callable[[Settings], AIProvider | None]
_FACTORIES: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    _FACTORIES[name] = factory


def build_provider(settings: Settings) -> AIProvider | None:
    name = settings.ai_provider
    if name not in _FACTORIES:
        raise ValueError(
            f"Unknown AI provider {name!r}; known: {', '.join(sorted(_FACTORIES))}"
        )
    return _FACTORIES[name](settings)


def _gemini(settings: Settings) -> AIProvider | None:
    if not settings.gemini_api_key:
        return None
    from app.modules.ai.gemini import Gemini  # noqa: PLC0415

    return Gemini(settings)


register_provider("gemini", _gemini)
register_provider("none", lambda _: None)
