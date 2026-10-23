"""One interview turn: answer (text or audio) in -> next spoken question out."""

from __future__ import annotations

import asyncio
import base64
import logging
import time

from app.core.config import Settings
from app.core.errors import DeadlineExceeded
from app.core.logging import log_event
from app.providers.base import LlmProvider, LlmTask, SttProvider, TtsProvider
from app.providers.errors import ProviderError, ProviderServerError
from app.schemas.common import QA, Meta
from app.schemas.turn import AnsweredOut, AnswerIn, QuestionOut, TurnRequest, TurnResponse
from app.services.answer_check import (
    AnswerStatus,
    NonAnswer,
    arabize_terms,
    classify_non_answer,
    nudge_for,
)
from app.services.audio import decode_audio
from app.services.errors_map import to_app_error
from app.services.interview_plan import QuestionPlan, plan_question
from app.services.prompt_builder import build_turn_messages
from app.services.prompts import PromptStore
from app.services.question_policy import TurnDecision, TurnQuestion, validate_turn
from app.services.text import clean_transcript, collapse_whitespace

logger = logging.getLogger(__name__)
FIXED_MODEL_ID = "fixed"


class TurnService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LlmProvider,
        stt: SttProvider,
        tts: TtsProvider,
        prompts: PromptStore,
    ) -> None:
        self._s = settings
        self._llm, self._stt, self._tts = llm, stt, tts
        self._prompt = prompts.get("discovery_turn")
        # The opening question never changes and holds no student data, so its
        # audio is generated once. Saves a TTS call on every interview.
        self._opening_audio: tuple[str, str] | None = None

    async def run(self, req: TurnRequest) -> TurnResponse:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._s.turn_deadline_seconds):
                response = await self._run(req, started)
        except TimeoutError:
            raise DeadlineExceeded("The turn took too long") from None
        except ProviderError as exc:
            raise to_app_error(exc) from None
        return response

    async def _run(self, req: TurnRequest, started: float) -> TurnResponse:
        answered: AnsweredOut | None = None
        conversation = list(req.history)
        answered_count = conversation[-1].order_index if conversation else 0
        attempt = 1
        judging = req.answer is not None
        dont_know = False

        if req.answer is not None:
            attempt = req.answer.attempt
            transcript = await self._transcript_of(req.answer)
            reason = classify_non_answer(transcript)
            dont_know = reason is NonAnswer.DONT_KNOW
            if reason is not None and not dont_know:
                # Silence / filler: no model call, the same question is asked again.
                return await self._retry_fixed(req, req.answer, transcript, started)
            # "I don't know" is a real answer: it is kept and the interview goes on (easier question).
            judging = not dont_know
            answered = AnsweredOut(order_index=req.answer.order_index, transcript=transcript)
            conversation.append(
                QA(
                    order_index=req.answer.order_index,
                    question_text=req.answer.question_text,
                    transcript=transcript,
                )
            )
            answered_count = req.answer.order_index

        final = answered_count >= req.max_questions
        if final and (req.answer is None or dont_know):
            return self._response(req, None, None, FIXED_MODEL_ID, started)  # nothing new to judge
        if final:
            # Last answer: the model only judges it. If it is real the interview is finished.
            decision = await self._judge_final(req, conversation, attempt)
            if decision.status is AnswerStatus.ACCEPTED:
                return self._response(req, answered, None, FIXED_MODEL_ID, started)
            return await self._retry_response(
                req, req.answer, decision, FIXED_MODEL_ID, started, heard=transcript
            )

        number = answered_count + 1
        if number == 1:
            opening = self._s.opening_question
            q, model_id = TurnQuestion(opening, self._s.opening_question_speech or opening), FIXED_MODEL_ID
        else:
            decision, model_id = await self._next_question(
                req, conversation, number, judging, attempt, dont_know
            )
            if decision.status is not AnswerStatus.ACCEPTED and req.answer is not None:
                return await self._retry_response(
                    req,
                    req.answer,
                    decision,
                    model_id,
                    started,
                    heard=answered.transcript if answered else None,
                )
            assert decision.question is not None
            q = decision.question

        audio_b64 = mime = None
        if req.speak:
            audio = await self._speak(q.speech, cacheable=number == 1)
            if audio:
                audio_b64, mime = audio
        question = QuestionOut(
            order_index=number, question_text=q.text, audio_base64=audio_b64, audio_mime_type=mime
        )
        return self._response(req, answered, question, model_id, started)

    # ---------------------------------------------------------------- steps
    async def _transcript_of(self, answer: AnswerIn) -> str | None:
        """The student's words, or None when nothing understandable was said."""
        if answer.transcript:
            return collapse_whitespace(answer.transcript)
        if not answer.audio_base64:
            return None
        audio = decode_audio(
            answer.audio_base64,
            answer.audio_mime_type or "",
            max_bytes=self._s.max_audio_bytes,
            max_seconds=self._s.max_audio_seconds,
        )
        text = clean_transcript(
            await self._stt.transcribe(audio.data, filename=audio.filename, mime_type=audio.mime_type)
        )
        return text[: self._s.max_text_chars] if text else None

    async def _next_question(
        self,
        req: TurnRequest,
        conversation: list[QA],
        number: int,
        judging: bool,
        attempt: int,
        dont_know: bool = False,
    ) -> tuple[TurnDecision, str]:
        plan = plan_question(
            number,
            req.max_questions,
            req.tracks,
            conversation,
            broad_questions=self._s.broad_questions,
        )
        messages = build_turn_messages(
            self._prompt,
            self._s,
            tracks=req.tracks,
            grade=req.grade,
            conversation=conversation,
            question_number=number,
            max_questions=req.max_questions,
            plan=plan,
            judging=judging,
            attempt=attempt,
            dont_know=dont_know,
        )
        previous = [qa.question_text for qa in conversation]
        result = await self._llm.generate_json(
            task=LlmTask.TURN,
            messages=messages,
            parse=lambda data: validate_turn(data, previous_questions=previous, judging=judging),
            context={"language": self._s.interview_language},
        )
        return result.value, result.model_id

    async def _judge_final(self, req: TurnRequest, conversation: list[QA], attempt: int) -> TurnDecision:
        """Judge the last answer. If the model is down the answer is accepted: a finished
        interview must not be lost because of a provider outage."""
        plan = QuestionPlan(kind="closing", focus="")
        messages = build_turn_messages(
            self._prompt,
            self._s,
            tracks=req.tracks,
            grade=req.grade,
            conversation=conversation,
            question_number=req.max_questions,
            max_questions=req.max_questions,
            plan=plan,
            judging=True,
            final=True,
            attempt=attempt,
        )
        try:
            result = await self._llm.generate_json(
                task=LlmTask.TURN,
                messages=messages,
                parse=lambda data: validate_turn(data, judging=True, need_question=False),
                context={"language": self._s.interview_language},
            )
        except ProviderError as exc:
            log_event(logger, logging.WARNING, "final_judge_skipped", reason=type(exc).__name__)
            return TurnDecision(AnswerStatus.ACCEPTED, None)
        return result.value

    # --------------------------------------------------------------- retries
    async def _retry_fixed(
        self,
        req: TurnRequest,
        answer: AnswerIn,
        heard: str | None,
        started: float,
    ) -> TurnResponse:
        """Not an answer (no model needed): fixed nudge + the same question again."""
        lang = self._s.interview_language
        nudge = nudge_for(lang, answer.attempt)
        base = answer.question_text
        speech = arabize_terms(base) if lang == "ar" else base
        decision = TurnDecision(
            AnswerStatus.NO_ANSWER, TurnQuestion(base, speech), TurnQuestion(nudge, nudge)
        )
        return await self._retry_response(req, answer, decision, FIXED_MODEL_ID, started, heard=heard)

    async def _retry_response(
        self,
        req: TurnRequest,
        answer: AnswerIn | None,
        decision: TurnDecision,
        model_id: str,
        started: float,
        heard: str | None = None,
    ) -> TurnResponse:
        assert answer is not None and decision.question is not None and decision.nudge is not None
        # The nudge is spoken first, then the question; one audio clip so the client plays it as is.
        audio_b64 = mime = None
        if req.speak:
            audio = await self._speak(f"{decision.nudge.speech} {decision.question.speech}", cacheable=False)
            if audio:
                audio_b64, mime = audio
        question = QuestionOut(
            order_index=answer.order_index,
            question_text=decision.question.text,
            audio_base64=audio_b64,
            audio_mime_type=mime,
            nudge_text=decision.nudge.text,
        )
        log_event(
            logger, logging.INFO, "answer_rejected", status=decision.status.value, attempt=answer.attempt
        )
        return self._response(
            req,
            None,
            question,
            model_id,
            started,
            status=decision.status,
            attempt=answer.attempt + 1,
            heard=heard,
        )

    async def warm_up(self, attempts: int = 4) -> None:
        """Synthesize the opening question at startup so question 1 always has a voice."""
        speech = self._s.opening_question_speech or self._s.opening_question
        for attempt in range(1, attempts + 1):
            if await self._speak(speech, cacheable=True):
                log_event(logger, logging.INFO, "opening_audio_ready", attempt=attempt)
                return
            await asyncio.sleep(2 * attempt)
        log_event(logger, logging.WARNING, "opening_audio_not_ready", attempts=attempts)

    async def _speak(self, text: str, *, cacheable: bool) -> tuple[str, str] | None:
        if cacheable and self._opening_audio:
            return self._opening_audio
        speech = None
        for attempt in (1, 2):
            try:
                speech = await asyncio.wait_for(self._tts.speak(text), timeout=self._s.tts_timeout_seconds)
                break
            except ProviderServerError as exc:
                # Network blip / 5xx: these fail fast, so one quick retry is cheap.
                log_event(logger, logging.WARNING, "tts_failed", reason=type(exc).__name__, attempt=attempt)
                if attempt == 2:
                    return None
                await asyncio.sleep(0.5)
            except (ProviderError, TimeoutError) as exc:
                # Speech is optional: the text question is always returned.
                log_event(logger, logging.WARNING, "tts_failed", reason=type(exc).__name__, attempt=attempt)
                return None
        if speech is None:
            return None
        encoded = (base64.b64encode(speech.data).decode("ascii"), speech.mime_type)
        if cacheable:
            self._opening_audio = encoded
        return encoded

    def _response(
        self,
        req: TurnRequest,
        answered: AnsweredOut | None,
        question: QuestionOut | None,
        model_id: str,
        started: float,
        *,
        status: AnswerStatus = AnswerStatus.ACCEPTED,
        attempt: int = 1,
        heard: str | None = None,
    ) -> TurnResponse:
        retry = status is not AnswerStatus.ACCEPTED
        return TurnResponse(
            interview_id=req.interview_id,
            answered=answered,
            next_question=question,
            finished=question is None,
            answer_status=status,
            retry=retry,
            attempt=attempt,
            heard=heard if retry else None,
            meta=Meta(
                prompt_version=self._prompt.label,
                model_id=model_id,
                latency_ms=round((time.perf_counter() - started) * 1000),
            ),
        )
