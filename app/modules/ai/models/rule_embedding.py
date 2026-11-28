from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RuleEmbedding(Base):
    __tablename__ = "rule_embeddings"

    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(120))
    vector_json: Mapped[str]
