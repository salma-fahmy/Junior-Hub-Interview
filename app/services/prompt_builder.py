"""Builds the chat messages sent to the LLM.

Layout keeps the STATIC part (instructions + track list) first and the
conversation last, so provider-side prompt caching can reuse the prefix.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.config import Settings
from app.providers.base import Message
from app.schemas.common import QA, Track
from app.services.interview_plan import QuestionPlan, render_plan
from app.services.prompts import Prompt
from app.services.text import neutralize_markup, truncate_words


def render_tracks(tracks: Sequence[Track], max_chars: int) -> str:
    return "\n".join(f"- {t.code} ({t.name}): {truncate_words(t.profile, max_chars)}" for t in tracks)


def render_conversation(items: Sequence[QA], max_chars: int) -> str:
    lines: list[str] = []
    for qa in items:
        lines.append(f"Question {qa.order_index}: {neutralize_markup(qa.question_text)}")
        answer = truncate_words(neutralize_markup(qa.transcript), max_chars)
        lines.append(f"<student_answer>{answer}</student_answer>")
    return "\n".join(lines)


def build_turn_messages(
    prompt: Prompt,
    settings: Settings,
    *,
    tracks: Sequence[Track],
    grade: int,
    conversation: Sequence[QA],
    question_number: int,
    max_questions: int,
    plan: QuestionPlan,
    judging: bool = False,
    final: bool = False,
    attempt: int = 1,
    dont_know: bool = False,
) -> list[Message]:
    """`judging`: the last item of `conversation` is a NEW answer the model must judge first.
    `final`: that answer was the last one, so only the judgement is needed (no next question)."""
    tracks_block = (
        render_tracks(tracks, settings.profile_max_chars_turn)
        if settings.include_tracks_in_turn
        else "(not provided)"
    )
    earlier = list(conversation[:-1] if judging else conversation)
    lines: list[str] = [f"Student grade: {grade}"]
    if final:
        lines.append("The interview has no more questions. Only judge the latest answer.")
    else:
        lines.append(f"This is question {question_number} of {max_questions}.")
        lines.extend(render_plan(plan))
    lines += [
        "",
        "Conversation so far:",
        render_conversation(earlier, settings.transcript_max_chars_in_prompt),
    ]
    if judging:
        lines += [
            "",
            "Latest exchange (judge this answer first):",
            render_conversation(conversation[-1:], settings.transcript_max_chars_in_prompt),
            f"This is attempt {attempt} at this question.",
        ]
        if final:
            lines.append("If the answer is real, set question_text and speech_text to empty strings.")
        else:
            lines.append(
                "If it is NOT a real answer, do not move on: "
                "write retry_message and ask the SAME question again."
            )
    else:
        lines.append("")
        if dont_know:
            lines.append(
                "The student said they do not know the answer to the last question. That is fine: "
                'answer_status must be "answered". Do NOT ask it again; ask a different, easier, '
                "more concrete question (a tiny example or two or three small choices)."
            )
        else:
            lines.append('There is no new answer to judge: answer_status must be "answered".')
    lines += ["", "Respond with the JSON object only."]
    return [
        {"role": "system", "content": prompt.render(tracks_block=tracks_block)},
        {"role": "user", "content": "\n".join(lines)},
    ]


def build_result_messages(
    prompt: Prompt,
    settings: Settings,
    *,
    tracks: Sequence[Track],
    grade: int,
    responses: Sequence[QA],
) -> list[Message]:
    system = prompt.render(
        tracks_block=render_tracks(tracks, settings.profile_max_chars_result),
        allowed_codes=", ".join(t.code for t in tracks),
    )
    user = "\n".join(
        [
            f"Student grade: {grade}",
            "",
            "Interview transcript:",
            render_conversation(responses, settings.transcript_max_chars_in_prompt),
            "",
            "Produce the recommendation now. Respond with the JSON object only.",
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
