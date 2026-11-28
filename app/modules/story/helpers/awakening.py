"""Versioned prerequisites shared by the player coach and the claim service."""

from app.modules.story.dto.awakening import Step
from app.modules.story.schemas.awakening import PathStep, Requirement, Status, StepId

AWAKENING_POINTS = 300


PATH_VERSION = "awakening-v1"


STEPS: dict[StepId, Step] = {
    "season_active": Step(
        "Complete new objectives while the season is active.", "season.schedule"
    ),
    "choose_character": Step(
        "Choose a character from the season roster.",
        "season.character",
        ("season_active",),
    ),
    "clear_duel": Step(
        "Escape the seeded story duel.", "story.clear", ("season_active",)
    ),
    "earn_points": Step(
        f"Reach {AWAKENING_POINTS} season points.", "season.points", ("season_active",)
    ),
    "claim_window": Step(
        "Claim during the season or the three days after it ends.", "season.schedule"
    ),
    "claim_form": Step(
        "Claim your chosen character's final form.",
        "season.awakening",
        ("choose_character", "clear_duel", "earn_points", "claim_window"),
    ),
    "final_form": Step(
        "Unlock the selected character's final form.",
        "story.ownership",
        ("claim_form",),
    ),
}


def requirements(selected: bool, cleared: bool, points: int) -> list[Requirement]:
    checklist: tuple[tuple[Requirement, bool], ...] = (
        ("choose_character", selected),
        ("clear_duel", cleared),
        ("earn_points", points >= AWAKENING_POINTS),
    )
    return [requirement for requirement, complete in checklist if not complete]


def resolve_path(
    missing: list[Requirement], season_active: bool, claim_open: bool, awakened: bool
) -> list[PathStep]:
    results: dict[StepId, PathStep] = {}
    incomplete: set[StepId] = set(missing)

    def visit(key: StepId) -> PathStep:
        if key in results:
            return results[key]
        step = STEPS[key]
        parents = tuple(map(visit, step.requires))
        prerequisites_met = all(parent.status == "complete" for parent in parents)
        status: Status
        if awakened:
            status = "complete"
        elif key == "season_active":
            status = "complete" if season_active else "blocked"
        elif (
            key in {"choose_character", "clear_duel", "earn_points"}
            and key not in incomplete
        ):
            status = "complete"
        elif key == "claim_window":
            status = "complete" if claim_open else "blocked"
        else:
            status = "ready" if prerequisites_met else "blocked"
        result = PathStep(
            id=key,
            text=step.text,
            source=step.source,
            requires=step.requires,
            status=status,
        )
        results[key] = result
        return result

    visit("final_form")
    return list(results.values())
