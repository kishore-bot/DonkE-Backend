"""In-memory `ObjectStore` for tests, injected through create_app or open_platform."""

from datetime import UTC, datetime


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[str, bytes, datetime]] = {}
        self.failing: set[str] = set()
        self.origins: list[str] = []

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = content_type, data, datetime.now(UTC)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def delete_many(self, keys: list[str]) -> list[str]:
        for key in keys:
            if key not in self.failing:
                self.objects.pop(key, None)
        return [key for key in keys if key in self.failing]

    async def keys_before(self, prefix: str, before: datetime) -> list[str]:
        return [
            key
            for key, (_, _, modified) in self.objects.items()
            if key.startswith(prefix) and modified < before
        ]

    async def url(self, key: str) -> str:
        return f"https://objects.example/{key}"

    async def prepare(self, cors_origins: list[str]) -> None:
        self.origins = cors_origins
