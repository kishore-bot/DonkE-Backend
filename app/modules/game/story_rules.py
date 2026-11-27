"""Story objectives and the minimal public projection of replay moments."""

from app.modules.game.schemas import StoryEvent, StoryObjective, StoryRoute

ROUTES: dict[StoryRoute, str] = {
    "seal": "Escape after a successful called Strike",
    "reef": "Escape after picking up at most one pile",
    "storm": "Escape after landing at least one Strike",
}


def public_event(event: dict, sequence: int, move: int) -> StoryEvent | None:
    match event["event"]:
        case "vettu":
            return StoryEvent(
                sequence=sequence,
                move=move,
                kind="strike",
                seat=event["cutter"],
                recipient=event["receiver"],
                cards=len(event["pile"]),
                led_suit=event["pile"][0]["card"]["suit"],
            )
        case "player_escaped":
            return StoryEvent(
                sequence=sequence, move=move, kind="escaped", seat=event["seat"]
            )
        case "game_finished":
            return StoryEvent(sequence=sequence, move=move, kind="finished")
        case "strike_called":
            return StoryEvent(
                sequence=sequence, move=move, kind="strike_called", seat=0, recipient=1
            )
        case "strike_call_resolved":
            return StoryEvent(
                sequence=sequence,
                move=move,
                kind="strike_resolved",
                success=event["success"],
            )
    return None


def objective(route: StoryRoute, events: tuple[StoryEvent, ...]) -> StoryObjective:
    if route == "seal":
        count = sum(
            event.kind == "strike_resolved" and event.success is True
            for event in events
        )
    elif route == "reef":
        count = sum(event.kind == "strike" and event.recipient == 0 for event in events)
    else:
        count = sum(event.kind == "strike" and event.seat == 0 for event in events)
    return StoryObjective(
        route=route,
        count=count,
        target=1,
        met=count <= 1 if route == "reef" else count >= 1,
    )
