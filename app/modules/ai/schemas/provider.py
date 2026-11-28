from pydantic import BaseModel, Field


class Choice(BaseModel):
    key: str = Field(max_length=40)
