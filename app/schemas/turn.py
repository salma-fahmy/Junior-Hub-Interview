"""POST /v1/discovery/turns."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from app.schemas.common import QA, ApiModel, Meta, Track
from app.services.answer_check import AnswerStatus


class AnswerIn(ApiModel):
    """The student's answer to the current question: typed text OR recorded audio."""

    order_index: int = Field(ge=1, le=50)
    question_text: str = Field(min_length=1, max_length=600)
    transcript: str | None = Field(default=None, max_length=1000)
    audio_base64: str | None = Field(default=None, max_length=25_000_000)
    audio_mime_type: str | None = Field(default=None, max_length=100)
    # How many times this same question has been asked (1 = first time). Send back the `attempt`
    # value of the previous response; only used to make a repeated question easier.
    attempt: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        # Neither text nor audio = the student did not answer: the service asks the question again.
        has_text = bool(self.transcript)
        has_audio = bool(self.audio_base64)
        if has_text and has_audio:
            raise ValueError("provide only one of transcript or audio_base64")
        if has_audio and not self.audio_mime_type:
            raise ValueError("audio_mime_type is required with audio_base64")
        return self


class TurnRequest(ApiModel):
    interview_id: str = Field(min_length=1, max_length=64)
    student_ref: str = Field(min_length=1, max_length=64)
    grade: int = Field(ge=1, le=13)
    tracks: list[Track] = Field(min_length=1, max_length=20)
    history: list[QA] = Field(default_factory=list, max_length=50)
    answer: AnswerIn | None = None
    max_questions: int = Field(default=10, ge=1, le=20)
    speak: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        indices = [item.order_index for item in self.history]
        if indices != sorted(set(indices)):
            raise ValueError("history.order_index must be strictly increasing")
        if self.answer and indices and self.answer.order_index <= indices[-1]:
            raise ValueError("answer.order_index must come after the history")
        codes = [t.code for t in self.tracks]
        if len(codes) != len(set(codes)):
            raise ValueError("track codes must be unique")
        return self


class AnsweredOut(ApiModel):
    order_index: int
    transcript: str


class QuestionOut(ApiModel):
    order_index: int
    question_text: str
    # Both are null when speech synthesis failed: the text is always present.
    audio_base64: str | None = None
    audio_mime_type: str | None = None
    # Only when the answer was NOT accepted: the short sentence telling the student to answer the
    # question. It is also spoken first in `audio_base64`. `question_text` is then the question
    # asked AGAIN (store that one as the question text of the next answer).
    nudge_text: str | None = None


class TurnResponse(ApiModel):
    interview_id: str
    answered: AnsweredOut | None = None
    next_question: QuestionOut | None = None
    finished: bool
    # `accepted`: the answer counts and the interview moved on.
    # `off_topic` / `no_answer`: NOT accepted. `answered` is null, `finished` is false, `next_question`
    # is the SAME question asked again (same order_index) and the history must not change.
    answer_status: AnswerStatus = AnswerStatus.ACCEPTED
    retry: bool = False
    # Value to send as `answer.attempt` with the next answer (1 after an accepted answer).
    attempt: int = 1
    # What was understood when the answer was not accepted (for display/debug; empty for silence).
    heard: str | None = None
    meta: Meta
