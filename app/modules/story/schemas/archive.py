from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.progression.schemas.content import CharacterPreview


class ArchiveChapter(BaseModel):
    id: str
    title: str


class CollectionEntry(BaseModel):
    season_id: UUID
    title: str
    ended_at: datetime
    pack_key: str
    character: CharacterPreview
    awakened: bool
    chapters: list[ArchiveChapter]
