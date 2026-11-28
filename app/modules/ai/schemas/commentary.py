from typing import Literal

from pydantic import BaseModel

from app.modules.identity.schemas.profile import Language


class Commentary(BaseModel):
    language: Language
    text: str
    source: Literal["script", "gemini"]
