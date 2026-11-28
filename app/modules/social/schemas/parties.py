from uuid import UUID

from pydantic import BaseModel

from app.modules.identity.schemas.profile import Profile


class PartyView(BaseModel):
    id: UUID
    leader_id: UUID
    members: list[Profile]
