import json

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai.dto.rule import Rule
from app.modules.ai.helpers.knowledge import RULES, sources
from app.modules.ai.models.rule_embedding import RuleEmbedding
from app.modules.ai.services.gateway import Gateway


async def reindex(gateway: Gateway, db: AsyncSession) -> int:
    vectors = await gateway.embeddings(
        [f"{rule.en} {rule.ml}" for rule in RULES], query=False
    )
    if vectors is None:
        raise AppError(503, "embedding_unavailable", "Rule embedding is unavailable")
    model = gateway.models.embedding
    for rule, vector in zip(RULES, vectors, strict=True):
        row = insert(RuleEmbedding).values(
            source=rule.source, model=model, vector_json=json.dumps(vector)
        )
        await db.execute(
            row.on_conflict_do_update(
                index_elements=[RuleEmbedding.source],
                set_={
                    "model": row.excluded.model,
                    "vector_json": row.excluded.vector_json,
                },
            )
        )
    return len(vectors)


async def ranked_rules(gateway: Gateway, question: str) -> list[Rule]:
    lexical = sources(question)
    if gateway.provider is None:
        return lexical
    model = gateway.models.embedding
    async with gateway.platform.sessions() as db:
        available = await db.scalar(
            select(RuleEmbedding.source).where(RuleEmbedding.model == model).limit(1)
        )
    if available is None:
        return lexical
    vectors = await gateway.embeddings([question], query=True)
    if vectors is None:
        return lexical
    query = text("""
        SELECT source
        FROM rule_embeddings
        WHERE model = :model
          AND CAST(vector_json AS vector) <=> CAST(:vector AS vector) <= 0.55
        ORDER BY CAST(vector_json AS vector) <=> CAST(:vector AS vector), source
        LIMIT 3
    """)
    async with gateway.platform.sessions() as db:
        semantic = list(
            await db.scalars(query, {"model": model, "vector": json.dumps(vectors[0])})
        )
    scores: dict[str, float] = {}
    for ordering in ([rule.source for rule in lexical], semantic):
        for index, key in enumerate(ordering, 1):
            scores[key] = scores.get(key, 0.0) + 1 / (60 + index)
    return sorted(
        (rule for rule in RULES if rule.source in scores),
        key=lambda rule: -scores[rule.source],
    )[:3]
