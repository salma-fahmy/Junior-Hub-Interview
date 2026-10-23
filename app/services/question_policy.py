"""What each question should explore, and the checks every question must pass."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.services.answer_check import AnswerStatus
from app.services.text import clean_spoken_text, question_marks
from app.services.track_knowledge import normalize_arabic

MAX_WORDS = 45

# One focus per question. Question 1 is the fixed opener (free time).
FOCUS_PLAN = (
    "free time: what they enjoy doing when they are not at school",
    "school: which school subjects they like and what they enjoy about them",
    "making things: do they prefer making things look good (drawing, designing, "
    "decorating) or figuring out how things work (fixing, building, puzzles)",
    "problem solving: a time something was hard or did not work, and what they did",
    "games and apps: games, apps or websites they love and what they like about them",
    "teamwork: whether they like working in a team or alone, and what role they take",
    "following a spark: dig deeper into the interest that has shown up most strongly so far",
    "numbers and patterns: whether they enjoy puzzles, numbers, collecting information or spotting patterns",
    "curiosity: something they have wondered how it works (phones, websites, robots, games)",
    "dream project: what they would love to create if they could make anything with technology",
)

_PERSONAL_INFO = re.compile(
    r"\b(?:what(?:'s| is) your (?:full |first |last )?name|your (?:full |first |last |sur)name"
    r"|where do you live|your (?:home )?address|(?:phone|mobile|telephone) (?:number|no)"
    r"|e-?mail|(?:which|what) school (?:do|are) you|name of your school|school name"
    r"|your school'?s? name|how old are you|your birthday|date of birth|password"
    r"|(?:instagram|snapchat|tiktok|facebook|whatsapp|social media) "
    r"(?:account|handle|username|name))\b",
    re.IGNORECASE,
)


# Same idea in Arabic (MSA and Egyptian/Gulf colloquial). Diacritics are removed before matching.
_PERSONAL_INFO_AR = re.compile(
    r"(?:اسمك|إسمك|اسم حضرتك|اسمكم|اسم عائلتك|اسم مدرستك|مدرستك اسمها|ما هي مدرستك|في أي مدرسة|في اي مدرسة"
    r"|ساكن فين|ساكنة فين|تسكن|تعيش فين|أين تسكن|اين تسكن|أين تعيش|اين تعيش|عنوانك|عنوان بيتك"
    r"|رقم (?:تليفونك|تلفونك|موبايلك|هاتفك|جوالك|تلفون)|رقمك|إيميلك|ايميلك|بريدك"
    r"|عندك كام سنة|عمرك كام|كم عمرك|كام سنة عمرك|سنك كام|عيد ميلادك|تاريخ ميلادك"
    r"|كلمة السر|كلمة المرور|الباسورد|باسوردك"
    r"|حسابك على|اكونتك|أكاونتك|يوزرك)"
)
_DIACRITICS = re.compile("[\u064b-\u0652\u0640]")


@dataclass(frozen=True)
class TurnQuestion:
    """What the student reads (may contain English programming terms) and what the TTS says."""

    text: str
    speech: str


@dataclass(frozen=True)
class TurnDecision:
    """What the model decided: was the answer real, and what to say next."""

    status: AnswerStatus
    question: TurnQuestion | None  # next question (accepted) or the question to ask again (retry)
    nudge: TurnQuestion | None = None  # short "please answer the question" sentence (retry only)


def focus_for(question_number: int, max_questions: int) -> str:
    if question_number >= max_questions:
        return FOCUS_PLAN[-1]
    return FOCUS_PLAN[min(max(question_number - 1, 0), len(FOCUS_PLAN) - 2)]


def validate_question(raw: str) -> str:
    """Return the cleaned question or raise ValueError (the model will be asked to repair)."""
    text = clean_spoken_text(raw)
    if not text:
        raise ValueError("question_text is empty")
    if len(text.split()) > MAX_WORDS:
        raise ValueError("the question is too long: use at most 35 words")
    if question_marks(text) > 2:
        raise ValueError("ask exactly one question")
    if _PERSONAL_INFO.search(text) or _PERSONAL_INFO_AR.search(_DIACRITICS.sub("", text)):
        raise ValueError("the question asks for personal information; ask about interests instead")
    return text


MAX_NUDGE_WORDS = 30
REPEAT_SIMILARITY = 0.7
_WORD = re.compile(r"[\w']+", re.UNICODE)
_STATUS_ALIASES = {
    "answered": AnswerStatus.ACCEPTED,
    "accepted": AnswerStatus.ACCEPTED,
    "ok": AnswerStatus.ACCEPTED,
    "off_topic": AnswerStatus.OFF_TOPIC,
    "offtopic": AnswerStatus.OFF_TOPIC,
    "no_answer": AnswerStatus.NO_ANSWER,
    "noanswer": AnswerStatus.NO_ANSWER,
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(normalize_arabic(text)) if len(w) > 1}


def is_repeat(question: str, previous: Sequence[str]) -> bool:
    """True when the new question is (nearly) one that was already asked."""
    new = _tokens(question)
    if len(new) < 4:
        return False
    for old_text in previous:
        old = _tokens(old_text)
        if old and len(new & old) / len(new | old) >= REPEAT_SIMILARITY:
            return True
    return False


def validate_nudge(raw: str) -> str:
    text = clean_spoken_text(raw)
    if not text:
        raise ValueError("retry_message is empty: tell the student, kindly, to answer the question")
    if len(text.split()) > MAX_NUDGE_WORDS:
        raise ValueError("retry_message is too long: use one short sentence")
    if _PERSONAL_INFO.search(text) or _PERSONAL_INFO_AR.search(_DIACRITICS.sub("", text)):
        raise ValueError("retry_message asks for personal information")
    return text


def validate_turn(
    data: dict[str, Any],
    *,
    previous_questions: Sequence[str] = (),
    judging: bool = False,
    need_question: bool = True,
) -> TurnDecision:
    """Parse the model's JSON.

    * ``judging``: there is a new student answer to judge. When False the status is always ACCEPTED.
    * ``need_question``: False on the final turn, where only the judgement matters.
    * Accepted -> a NEW question (not a repeat). Not accepted -> a nudge + the question asked again.
    """
    raw_status = (
        str(data.get("answer_status") or "answered").strip().lower().replace("-", "_").replace(" ", "_")
    )
    if raw_status not in _STATUS_ALIASES:
        raise ValueError("answer_status must be one of: answered, off_topic, no_answer")
    status = _STATUS_ALIASES[raw_status] if judging else AnswerStatus.ACCEPTED

    if status is AnswerStatus.ACCEPTED and not need_question:
        return TurnDecision(status, None)

    text = validate_question(str(data["question_text"]))
    raw_speech = data.get("speech_text")
    speech = validate_question(str(raw_speech)) if raw_speech else text
    question = TurnQuestion(text=text, speech=speech)

    if status is AnswerStatus.ACCEPTED:
        if is_repeat(text, previous_questions):
            raise ValueError("this question repeats an earlier one: ask about something different")
        return TurnDecision(status, question)

    message = validate_nudge(str(data.get("retry_message") or ""))
    raw_message_speech = data.get("retry_speech")
    message_speech = validate_nudge(str(raw_message_speech)) if raw_message_speech else message
    return TurnDecision(status, question, TurnQuestion(text=message, speech=message_speech))
