from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    admin_id: UUID
    action: str
    reason: str
    request_id: UUID
    at: datetime
