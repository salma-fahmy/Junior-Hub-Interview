"""Decides what question N should be about.

Shape of an interview (example with 7 questions, 2 broad):

    Q1       fixed opener (free time)                 - broad
    Q2       school subjects                          - broad
    Q3..Q6   DEEP DIVES into the tracks the student's own answers point to
    Q7       dream project, flavoured by the leading track

Deep dives alternate between the leading track and the runner-up so the result step can tell
close tracks apart (e.g. Frontend vs UI/UX), and come back to the leader with a new angle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.schemas.common import QA, Track
from app.services.question_policy import FOCUS_PLAN, focus_for
from app.services.track_knowledge import knowledge_for, probes_for, signal_score

# Which ranked candidate to dig into at deep question 0, 1, 2...: leader, runner-up, leader, ...
_PICK_ORDER = (0, 1, 0, 1, 2, 0)


@dataclass(frozen=True)
class QuestionPlan:
    kind: Literal["broad", "deep", "closing"]
    focus: str
    track: Track | None = None
    what_it_is: str = ""
    probes: tuple[str, ...] = ()
    also_showing: tuple[str, ...] = ()  # other tracks the answers point to (context only)


def rank_tracks(tracks: Sequence[Track], answers: Sequence[QA], rotate: int = 0) -> list[tuple[Track, int]]:
    """Tracks the student's answers point to first (score desc); unscored ones after, rotated."""
    scored = [(t, signal_score(t, answers)) for t in tracks]
    hits = sorted((p for p in scored if p[1] > 0), key=lambda p: -p[1])  # sort is stable
    rest = [p for p in scored if p[1] == 0]
    if rest:
        shift = (rotate * 3) % len(rest)
        rest = rest[shift:] + rest[:shift]
    return hits + rest


def _describe(track: Track) -> str:
    known = knowledge_for(track)
    return known.what_it_is if known else track.profile.strip().rstrip(".")


def plan_question(
    number: int,
    max_questions: int,
    tracks: Sequence[Track],
    answers: Sequence[QA],
    *,
    broad_questions: int = 2,
) -> QuestionPlan:
    leaders = rank_tracks(tracks, answers)
    lead_hint = ""
    if leaders and leaders[0][1] > 0:
        lead_hint = (
            f" The answers so far point most to: {_describe(leaders[0][0])}. "
            "If it fits, shape the dream around that kind of work, without naming it as a field."
        )

    if number >= max_questions:
        return QuestionPlan(kind="closing", focus=FOCUS_PLAN[-1] + "." + lead_hint)
    if number <= broad_questions or not tracks:
        return QuestionPlan(kind="broad", focus=focus_for(number, max_questions))

    deep_index = number - broad_questions - 1
    ranked = rank_tracks(tracks, answers, rotate=deep_index)
    pick = _PICK_ORDER[deep_index % len(_PICK_ORDER)] % len(ranked)
    track = ranked[pick][0]
    also = tuple(t.name for t, score in ranked[:3] if score > 0 and t.code != track.code)
    return QuestionPlan(
        kind="deep",
        focus=f"deep dive into {track.name}",
        track=track,
        what_it_is=_describe(track),
        probes=probes_for(track),
        also_showing=also,
    )


def render_plan(plan: QuestionPlan) -> list[str]:
    """Lines for the prompt that tell the model what this question must do."""
    if plan.kind != "deep" or plan.track is None:
        return [
            f"Suggested focus for this question: {plan.focus}.",
            "(Use the suggested focus unless the latest answer calls for a natural follow-up.)",
        ]
    lines = [
        "Question type: DEEP DIVE. This must be a specific, concrete question, NOT a general one.",
        f"Area to dig into: {plan.track.name} - {plan.what_it_is}.",
    ]
    if plan.also_showing:
        lines.append(
            f"The student's answers also point to: {', '.join(plan.also_showing)} "
            "(context only: do not ask about them now)."
        )
    lines.append("Pick ONE angle that has NOT been covered yet in the conversation:")
    lines.extend(f"  {i}. {probe}" for i, probe in enumerate(plan.probes, start=1))
    lines.append(
        "Build on a detail from the latest answer when you can. Ask about a real situation, an example or a "
        "'would you rather' between two concrete things. Never name the area as a field, option or track."
    )
    return lines
