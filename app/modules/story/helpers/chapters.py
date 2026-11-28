from app.core.errors import AppError
from app.modules.story.dto.chapter import Chapter

OPENING_CHAPTER = "trial"


CHAPTERS = {
    "grimoire-awakening-v1": (
        Chapter(OPENING_CHAPTER, 1, "Arena Trial", "The Arena Keeper", 5, 20, 40),
        Chapter(
            "rival",
            2,
            "Grimoire Rivalry",
            "The Rune Tactician",
            13,
            20,
            35,
            OPENING_CHAPTER,
        ),
        Chapter(
            "finale", 3, "Awakening Trial", "The Hollow Warden", 37, 30, 55, "rival"
        ),
    ),
    "skybound-voyage-v1": (
        Chapter(OPENING_CHAPTER, 1, "Deck Trial", "The Storm Captain", 41, 20, 40),
        Chapter(
            "rival",
            2,
            "Crosswind Duel",
            "The Tide Navigator",
            61,
            20,
            35,
            OPENING_CHAPTER,
        ),
        Chapter(
            "finale", 3, "Eye of the Storm", "The Gale Warden", 83, 30, 55, "rival"
        ),
    ),
}


CHAPTERS["grimoire-awakening-v2"] = CHAPTERS["grimoire-awakening-v1"]


CHAPTERS["skybound-voyage-v2"] = CHAPTERS["skybound-voyage-v1"]


def chapter_for(pack: str, chapter_id: str = OPENING_CHAPTER) -> Chapter:
    chapter = next(
        (entry for entry in CHAPTERS.get(pack, ()) if entry.id == chapter_id), None
    )
    if chapter is None:
        raise AppError(404, "chapter_not_found", "This story chapter is unavailable")
    return chapter
