"""Object storage behind one interface, chosen by configuration.

Code that stores files depends on `ObjectStore` and receives an instance through
`Platform.storage`; it never names a vendor. `DONKE_STORAGE_PROVIDER` picks the
backend from the registry. To add one, implement `ObjectStore` and call
`register_storage("name", factory)` before the platform opens.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.core.config import Settings
from app.core.errors import AppError


class ObjectStore(Protocol):
    async def upload(self, key: str, data: bytes, content_type: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def delete_many(self, keys: list[str]) -> list[str]:
        """Delete keys and return those that could not be deleted."""
        ...

    async def keys_before(self, prefix: str, before: datetime) -> list[str]:
        """Keys under `prefix` last modified before `before`."""
        ...

    async def url(self, key: str) -> str:
        """A short-lived URL a browser can read the object from."""
        ...

    async def prepare(self, cors_origins: list[str]) -> None:
        """Create the container if missing and allow browser reads from origins."""
        ...


StorageFactory = Callable[[Settings], ObjectStore | None]
_FACTORIES: dict[str, StorageFactory] = {}


def register_storage(name: str, factory: StorageFactory) -> None:
    _FACTORIES[name] = factory


def build_storage(settings: Settings) -> ObjectStore | None:
    """The configured store, or None when it is switched off or unconfigured."""
    name = settings.storage_provider
    if name not in _FACTORIES:
        raise ValueError(
            f"Unknown storage provider {name!r}; known: {', '.join(sorted(_FACTORIES))}"
        )
    return _FACTORIES[name](settings)


def require_storage(storage: ObjectStore | None) -> ObjectStore:
    if storage is None:
        raise AppError(
            503, "media_unavailable", "Season object storage is not configured"
        )
    return storage


def _s3(settings: Settings) -> ObjectStore | None:
    if not settings.season_media_bucket:
        return None
    from app.core.s3_storage import S3Store  # noqa: PLC0415 - boto3 loads on use

    return S3Store(settings)


register_storage("s3", _s3)
register_storage("none", lambda _: None)
