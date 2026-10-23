"""Offline providers: no network, deterministic. For tests and UI work (FAKE_MODELS=true)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from app.providers.base import LlmResult, LlmTask, Message, SpeechAudio, T
from app.services.wav import silent_wav

# (shown on screen, read aloud)
_QUESTIONS = (
    (
        "رائع! ما المواد الدراسية التي تحبها أكثر، ولماذا؟",
        "رَائِع! مَا المَوَادُّ الدِّرَاسِيَّةُ الَّتِي تُحِبُّهَا أَكْثَر، وَلِمَاذَا؟",
    ),
    (
        "هل تحب أن تجعل الأشياء تبدو جميلة، أم تحب أن تفهم كيف تعمل؟",
        "هَلْ تُحِبُّ أَنْ تَجْعَلَ الأَشْيَاءَ تَبْدُو جَمِيلَة، أَمْ تُحِبُّ أَنْ تَفْهَمَ كَيْفَ تَعْمَل؟",
    ),
    ("احكِ لي عن مرة كان فيها شيء صعب، وماذا فعلت؟", "احْكِ لِي عَنْ مَرَّةٍ كَانَ فِيهَا شَيْءٌ صَعْب، وَمَاذَا فَعَلْت؟"),
    (
        "ما الـ Games أو الـ Apps التي تحبها، وما الممتع فيها؟",
        "مَا الجيمز أَوِ الآبس الَّتِي تُحِبُّهَا، وَمَا المُمْتِعُ فِيهَا؟",
    ),
    ("هل تحب العمل في فريق أم وحدك؟", "هَلْ تُحِبُّ العَمَلَ فِي فَرِيقٍ أَمْ وَحْدَك؟"),
    ("ما الشيء الذي تتساءل كيف يعمل؟", "مَا الشَّيْءُ الَّذِي تَتَسَاءَلُ كَيْفَ يَعْمَل؟"),
    ("لو تستطيع أن تصنع أي شيء بالـ Coding، ماذا ستصنع؟", "لَوْ تَسْتَطِيعُ أَنْ تَصْنَعَ أَيَّ شَيْءٍ بِالكودينج، مَاذَا سَتَصْنَع؟"),
    ("هل أصلحت شيئًا بنفسك من قبل؟ احكِ لي كيف فعلتها.", "هَلْ أَصْلَحْتَ شَيْئًا بِنَفْسِكَ مِنْ قَبْل؟ احْكِ لِي كَيْفَ فَعَلْتَهَا."),
    ("أي تطبيق تستخدمه كل يوم، وماذا تغير فيه؟", "أَيُّ تَطْبِيقٍ تَسْتَخْدِمُهُ كُلَّ يَوْم، وَمَاذَا تُغَيِّرُ فِيه؟"),
    ("ما اللغز الذي أعجبك أكثر من غيره؟", "مَا اللُّغْزُ الَّذِي أَعْجَبَكَ أَكْثَرَ مِنْ غَيْرِه؟"),
)


_QUESTIONS_EN = (
    "Nice! Which school subjects do you enjoy the most, and why?",
    "Do you like making things look good, or figuring out how they work?",
    "Can you tell me about a time something was hard and what you did?",
    "What games or apps do you love, and what makes them fun?",
    "Do you prefer working in a team or on your own?",
    "What have you been curious about lately?",
    "If you could build anything with technology, what would it be?",
    "Have you ever fixed something yourself? Tell me how you did it.",
    "Which app do you use every day, and what would you change in it?",
    "Which puzzle did you enjoy the most, and why?",
)


class FakeLlm:
    model_id = "fake-llm"

    def __init__(self, language: str = "ar") -> None:
        self._en = language == "en"

    def _turn(self, content: str) -> dict[str, Any]:
        """Deterministic stand-in for the real judge. Marker `OFFTOPIC` in the latest answer = off topic."""
        answers = content.count("<student_answer>")
        judged = "Latest exchange" in content
        final = "Only judge the latest answer" in content
        status = "answered"
        question = ""
        if judged:
            latest = content.split("Latest exchange", 1)[1]
            question = (re.search(r"Question \d+: (.+)", latest) or [None, ""])[1].strip()
            if "OFFTOPIC" in latest:
                status = "off_topic"
        if final and status == "answered":
            return {"answer_status": status, "question_text": "", "speech_text": ""}
        if status != "answered":
            msg = (
                "I get it, but please answer the question."
                if self._en
                else "فهمت، لكن أحتاج أن تجاوب على السؤال."
            )
            return {
                "answer_status": status,
                "retry_message": msg,
                "retry_speech": None if self._en else msg,
                "question_text": question or "?",
                "speech_text": None if self._en else question,
            }
        if self._en:
            return {"answer_status": status, "question_text": _QUESTIONS_EN[answers % len(_QUESTIONS_EN)]}
        text, speech = _QUESTIONS[answers % len(_QUESTIONS)]
        return {"answer_status": status, "question_text": text, "speech_text": speech}

    async def generate_json(
        self,
        *,
        task: LlmTask,
        messages: list[Message],
        parse: Callable[[dict[str, Any]], T],
        context: Mapping[str, Any] | None = None,
    ) -> LlmResult[T]:
        if task is LlmTask.TURN:
            data = self._turn(messages[-1]["content"])
        else:
            codes = list((context or {}).get("track_codes", []))[:3]
            data = {
                "recommendations": [
                    {
                        "track_code": code,
                        "match_percent": pct,
                        "reason": (
                            f"You showed real interest that fits {code.title()}."
                            if self._en
                            else f"أظهرت اهتمامًا حقيقيًا يناسب {code.title()}."
                        ),
                    }
                    for code, pct in zip(codes, (86, 74, 61), strict=False)
                ],
                "summary": (
                    "Thank you for the nice chat! You love creating and solving problems. "
                    "These tracks fit what you told us. Have fun exploring them!"
                )
                if self._en
                else (
                    "شكرًا لك على هذه الدردشة الجميلة! "
                    "أنت تحب الإبداع وحل المشكلات، وهذه الـ Tracks تناسب ما قلته لنا. استمتع باستكشافها!"
                ),
                "summary_speech": None
                if self._en
                else (
                    "شُكْرًا لَكَ عَلَى هَذِهِ الدَّرْدَشَةِ الجَمِيلَة! "
                    "أَنْتَ تُحِبُّ الإِبْدَاعَ وَحَلَّ المُشْكِلَات، وَهَذِهِ التراكس تُنَاسِبُ مَا قُلْتَهُ لَنَا. اسْتَمْتِعْ بِاسْتِكْشَافِهَا!"
                ),
            }
        return LlmResult(parse(data), self.model_id)


class FakeStt:
    """Audio starting with b'TEXT:' is returned as that text; anything else is canned."""

    async def transcribe(self, audio: bytes, *, filename: str, mime_type: str) -> str:
        if audio.startswith(b"TEXT:"):
            return audio[5:].decode("utf-8", errors="ignore")
        return "بحب أعمل Games صغيرة وأصلح الكمبيوتر."


class FakeTts:
    async def speak(self, text: str) -> SpeechAudio:
        return SpeechAudio(silent_wav(), "audio/wav")
