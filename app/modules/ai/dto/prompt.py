from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prompt:
    id: str
    version: int
    digest: str
    text: str

    @property
    def label(self) -> str:
        return f"{self.id}@{self.version}"
