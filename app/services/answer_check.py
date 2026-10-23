# ruff: noqa: E501
"""Deciding whether the student really ANSWERED, and what to say when they did not.

Two layers protect the interview from moving on after a non-answer:

1. This module (no model call, instant): silence, noise and filler sounds are caught here. The
   service answers with a spoken nudge and asks the same question again. "I don't know" is NOT
   rejected: it is a real answer from a beginner, so the interview continues with an easier question.
2. The turn prompt (same model call that writes the next question): it also judges whether the
   latest answer is on topic and returns ``answer_status``. Off-topic answers are caught there.

Nothing in a rejected answer is stored: the caller keeps the history unchanged and the same
question is asked again.
"""

from __future__ import annotations

import re
from enum import StrEnum

from app.services.text import collapse_whitespace
from app.services.track_knowledge import normalize_arabic


class AnswerStatus(StrEnum):
    ACCEPTED = "accepted"  # a real answer: the interview moves on
    OFF_TOPIC = "off_topic"  # said something, but not an answer to the question
    NO_ANSWER = "no_answer"  # silence, noise, filler or "I don't know"


class NonAnswer(StrEnum):
    SILENCE = "silence"  # nothing was said / nothing understood
    # "مش عارف", "I don't know": a legitimate answer. The interview continues with an easier question.
    DONT_KNOW = "dont_know"


# ------------------------------------------------------------ non-answer detection
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)

# Whole-reply patterns (after normalisation). Kept strict on purpose: only clear non-answers.
_DONT_KNOW = re.compile(
    r"(?:"
    r"(?:مش|ما|لا) (?:عارف|عارفه|اعرف|اعلم|متاكد|متاكده|فاكر|فاكره)(?: (?:والله|بصراحه|خالص|حاجه|اقول|اجاوب|ايه|اجاوب ايه|اقول ايه))*"
    r"|معرفش(?: (?:والله|خالص|بصراحه))*|مش فاكر|مليش فكره|ملياش فكره|لا فكره لدي|ما عندي فكره|معنديش فكره"
    r"|ولا حاجه|ولا شيء|لا شيء|لا شي|مفيش|مافيش|ما في شي"
    r"|(?:i )?(?:dont|do not) (?:really )?know|idk|no idea|not sure|i(?: am|m) not sure|nothing|pass"
    r"|i cant (?:think|remember)|no comment|nope"
    r")"
)
_FILLER_WORDS = frozenset(
    {
        "امم",
        "اممم",
        "ممم",
        "همم",
        "اه",
        "اها",
        "ها",
        "هاه",
        "هه",
        "ايه",
        "يعني",
        "طيب",
        "ااا",
        "اا",
        "um",
        "umm",
        "uh",
        "uhh",
        "hmm",
        "hm",
        "er",
        "ah",
        "ok",
        "okay",
        "yeah",
        "so",
        "well",
    }
)


def _plain(text: str) -> str:
    text = normalize_arabic(text).replace("'", "").replace("\u2019", "")
    return collapse_whitespace(_PUNCT.sub(" ", text)).strip()


def classify_non_answer(transcript: str | None) -> NonAnswer | None:
    """Return why this is not an answer, or None when it looks like a real answer."""
    if transcript is None:
        return NonAnswer.SILENCE
    plain = _plain(transcript)
    if sum(ch.isalnum() for ch in plain) < 2:
        return NonAnswer.SILENCE
    if _DONT_KNOW.fullmatch(plain):
        return NonAnswer.DONT_KNOW
    if all(word in _FILLER_WORDS for word in plain.split()):
        return NonAnswer.SILENCE
    return None


# ------------------------------------------------------------------ retry wording
# (display text, spoken text). Nudges contain no Latin letters, so they are spoken as written.
_NUDGES: dict[str, dict[str, tuple[str, ...]]] = {
    "ar": {
        "first": ("لم أسمع إجابة واضحة. من فضلك جاوب على السؤال.",),
        "again": ("خذ وقتك، وحتى لو كانت إجابتك قصيرة قلها بكلماتك. سأعيد السؤال.",),
    },
    "en": {
        "first": ("I didn't hear a clear answer. Please answer the question.",),
        "again": (
            "Take your time. Even a short answer in your own words is fine. Here is the question again.",
        ),
    },
}


def nudge_for(language: str, attempt: int) -> str:
    """The spoken/displayed sentence telling the student to answer the question."""
    table = _NUDGES.get(language, _NUDGES["en"])
    return table["first"][0] if attempt <= 1 else table["again"][0]


# ------------------------------------------------- English terms -> Arabic pronunciation
# Orpheus (Arabic) cannot read Latin letters, so a question shown with English terms must be
# re-written in Arabic script before it is spoken. Longest terms first.
_TERMS: dict[str, str] = {
    "ui/ux": "يو آي يو إكس",
    "cybersecurity": "سايبر سيكيوريتي",
    "frontend": "فرونت إند",
    "backend": "باك إند",
    "website": "ويب سايت",
    "websites": "ويب سايتس",
    "minecraft": "ماين كرافت",
    "photoshop": "فوتوشوب",
    "instagram": "إنستجرام",
    "youtube": "يوتيوب",
    "tiktok": "تيك توك",
    "roblox": "روبلوكس",
    "fortnite": "فورتنايت",
    "scratch": "سكراتش",
    "arduino": "أردوينو",
    "android": "أندرويد",
    "iphone": "آيفون",
    "coding": "كودينج",
    "python": "بايثون",
    "design": "ديزاين",
    "mobile": "موبايل",
    "robot": "روبوت",
    "robots": "روبوتس",
    "canva": "كانفا",
    "games": "جيمز",
    "game": "جيم",
    "apps": "آبس",
    "app": "آب",
    "data": "داتا",
    "bug": "باج",
    "bugs": "باجز",
    "ai": "إيه آي",
    "pubg": "ببجي",
    "fifa": "فيفا",
}
_TERM_RE = re.compile(
    r"(?:ال[ـ]?\s*)?(?<![A-Za-z])("
    + "|".join(re.escape(k) for k in sorted(_TERMS, key=len, reverse=True))
    + r")(?![A-Za-z])",
    re.IGNORECASE,
)


def arabize_terms(text: str) -> str:
    """Replace known English terms with how an Arab programmer says them ('الـ Game' -> 'الجيم')."""

    def swap(match: re.Match[str]) -> str:
        spoken = _TERMS[match.group(1).lower()]
        return ("ال" + spoken) if match.group(0).startswith("ال") else spoken

    return collapse_whitespace(_TERM_RE.sub(swap, text))
