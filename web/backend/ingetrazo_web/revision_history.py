"""Undo, redo and retention, worked out from a document's revisions.

Every edit is a new revision, and Undo/Redo are *also* new revisions (a restore of an
earlier state), so the history is append-only. To step back and forth like an editor
does, each undo/redo revision records the move it made (``history: {"move", "to"}``); the
position in the timeline is rebuilt by replaying them, which makes it the same for every
browser and survive reloads.

A normal edit starts a new state and drops any redo path; an undo or redo moves the
position to the state of the revision it restored. A restore made by hand (``Restore as
new revision``) records no move, so it counts as an ordinary edit.
"""
from __future__ import annotations

from typing import Any

#: The fewest revisions a retention limit may keep: below this, Undo would be pointless.
MIN_KEPT = 5


def undo_state(revisions: list[dict[str, Any]]) -> dict[str, Any]:
    """``{"undo_to": revision | None, "redo_to": revision | None, "position", "states"}``."""
    states: list[int] = []
    position = -1
    alias: dict[int, int] = {}                    # revision number -> index of the state its content is
    for revision in sorted(revisions, key=lambda item: item["number"]):
        number = int(revision["number"])
        move = revision.get("history") or {}
        target = alias.get(int(move["to"])) if move.get("to") is not None else None
        if move.get("move") in ("undo", "redo") and target is not None:
            position = target
            alias[number] = target
        else:                                     # an ordinary edit: a new state, and the redo path is gone
            states = states[:position + 1] + [number]
            position += 1
            alias[number] = position
    return {
        "undo_to": states[position - 1] if position > 0 else None,
        "redo_to": states[position + 1] if 0 <= position + 1 < len(states) else None,
        "position": position,
        "states": len(states),
        "state_revisions": states,
    }


def revisions_to_prune(revisions: list[dict[str, Any]], keep: int) -> list[int]:
    """Revision numbers that may be deleted so about ``keep`` remain.

    Always kept: the first revision; the newest ``keep``; the states Undo and Redo can reach
    (the last ``keep`` states of the timeline, including everything ahead of the current
    position, since an undo makes the edits it stepped over the redo path); and every
    revision an undo or redo among the kept ones points back to. Without those, stepping
    back through history would eat the very edits it needs to return to.
    """
    if keep <= 0:
        return []
    by_number = {int(item["number"]): item for item in revisions}
    numbers = sorted(by_number)
    if not numbers:
        return []
    state = undo_state(revisions)
    window = state["state_revisions"][max(0, state["position"] - keep + 1):]
    protected = set(numbers[-keep:]) | {numbers[0]} | set(window)
    pending = list(protected)
    while pending:
        target = (by_number[pending.pop()].get("history") or {}).get("to")
        if target is not None and int(target) in by_number and int(target) not in protected:
            protected.add(int(target))
            pending.append(int(target))
    return [number for number in numbers if number not in protected]


def effective_keep(value: int) -> int:
    """The retention limit in force: 0 keeps everything, anything smaller than MIN_KEPT is raised to it."""
    return 0 if value <= 0 else max(MIN_KEPT, value)
