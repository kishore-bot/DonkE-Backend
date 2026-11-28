from pydantic import BaseModel

from app.modules.ai.schemas.source import Source
from app.modules.identity.schemas.profile import Language
from app.modules.matches.schemas.persona import Persona


class RivalView(BaseModel):
    persona: Persona
    name: str
    games: int
    wins: int
    losses: int
    taunt: str
    source: Source


class PersonaLines(BaseModel):
    language: Language
    personas: dict[Persona, dict[str, str]]
    source: Source
