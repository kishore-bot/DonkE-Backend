from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.schemas.profile import Profile


@dataclass(frozen=True, slots=True)
class Principal:
    profile: Profile
    session_id: UUID
