"""Deep, track-specific questions and the shape of the interview plan."""

import pytest

from app.schemas.common import QA, Track
from app.services.answer_check import AnswerStatus, arabize_terms
from app.services.interview_plan import plan_question, render_plan
from app.services.question_policy import is_repeat, validate_turn
from app.services.track_knowledge import knowledge_for, probes_for, signal_score

TRACK_LIST = [
    Track(code=c, name=n, profile=f"{n} track")
    for c, n in [
        ("FRONTEND", "Frontend"),
        ("BACKEND", "Backend"),
        ("UIUX", "UI/UX"),
        ("DATA", "Data"),
        ("MOBILE", "Mobile"),
        ("GAMES", "Games"),
        ("AI", "AI"),
        ("CYBER", "Cyber Security"),
    ]
]


def qa(n, text):
    return QA(order_index=n, question_text=f"Q{n}?", transcript=text)


def test_every_known_track_has_several_concrete_probes():
    for t in TRACK_LIST:
        assert knowledge_for(t) is not None, t.code
        assert len(probes_for(t)) >= 3


def test_unknown_track_gets_probes_from_its_profile():
    robotics = Track(code="ROBOTICS", name="Robotics", profile="Building robots with sensors and motors.")
    probes = probes_for(robotics)
    assert len(probes) >= 3 and "sensors and motors" in probes[0]


def test_arabic_answers_point_to_the_right_track():
    answers = [qa(1, "بحب ألعب ماين كرافت وأعمل شخصيات"), qa(2, "وبحب أتفرج على الاحصائيات")]
    scores = {t.code: signal_score(t, answers) for t in TRACK_LIST}
    assert scores["GAMES"] > 0 and scores["DATA"] > 0
    assert scores["GAMES"] == max(scores.values())


def test_first_questions_are_broad_then_deep_then_closing():
    answers = [qa(1, "بحب الرسم والتصميم")]
    assert plan_question(2, 7, TRACK_LIST, answers).kind == "broad"
    deep = plan_question(3, 7, TRACK_LIST, answers)
    assert deep.kind == "deep" and deep.track is not None and len(deep.probes) >= 3
    assert plan_question(7, 7, TRACK_LIST, answers).kind == "closing"


def test_deep_dive_follows_the_students_interest_then_alternates():
    answers = [qa(1, "بحب ألعب ماين كرافت"), qa(2, "وبرسم شخصيات وألوان وتصميم")]
    first = plan_question(3, 7, TRACK_LIST, answers)
    second = plan_question(4, 7, TRACK_LIST, answers)
    third = plan_question(5, 7, TRACK_LIST, answers)
    assert first.track.code == third.track.code  # back to the leader with a new angle
    assert second.track.code != first.track.code  # runner-up in between
    assert first.track.code in {"GAMES", "UIUX"}


def test_no_signal_still_gives_a_deep_question_on_some_track():
    plan = plan_question(3, 7, TRACK_LIST, [qa(1, "مش عارف")])
    assert plan.kind == "deep" and plan.track in TRACK_LIST


def test_rendered_deep_prompt_asks_for_a_concrete_question_not_a_general_one():
    text = "\n".join(render_plan(plan_question(3, 7, TRACK_LIST, [qa(1, "بحب الموبايل")])))
    assert "DEEP DIVE" in text and "NOT a general one" in text and "1. " in text


def test_repeat_guard():
    assert is_repeat("ما أكثر شيء تحب أن تفعله في وقت الفراغ؟", ["ما أكثر شيء تحب أن تفعله في وقت الفراغ؟"])
    assert not is_repeat("هل تحب أن ترسم شاشات التطبيقات؟", ["ما أكثر شيء تحب أن تفعله في وقت الفراغ؟"])


def test_validate_turn_rejects_a_repeated_question_but_allows_asking_it_again_after_off_topic():
    prev = ["What is the thing you enjoy most in your free time?"]
    with pytest.raises(ValueError):
        validate_turn(
            {"answer_status": "answered", "question_text": prev[0]}, previous_questions=prev, judging=True
        )
    d = validate_turn(
        {
            "answer_status": "off_topic",
            "retry_message": "Please answer the question.",
            "question_text": prev[0],
        },
        previous_questions=prev,
        judging=True,
    )
    assert d.status is AnswerStatus.OFF_TOPIC and d.nudge and d.question


def test_off_topic_without_a_nudge_is_rejected():
    with pytest.raises(ValueError):
        validate_turn({"answer_status": "off_topic", "question_text": "What do you enjoy?"}, judging=True)


def test_status_is_ignored_when_there_is_no_new_answer():
    d = validate_turn({"answer_status": "off_topic", "question_text": "What do you enjoy?"}, judging=False)
    assert d.status is AnswerStatus.ACCEPTED


def test_arabize_terms_for_speech():
    assert arabize_terms("هل تحب الـ Game أو Minecraft؟") == "هل تحب الجيم أو ماين كرافت؟"


def _turn_prompt(**kw):
    from pathlib import Path

    from app.core.config import Settings
    from app.services.prompt_builder import build_turn_messages
    from app.services.prompts import PromptStore

    settings = Settings(_env_file=None, app_env="test", fake_models=True, auth_disabled=True)
    prompt = PromptStore(Path("prompts"), {"discovery_turn": "v1", "discovery_result": "v1"}).get(
        "discovery_turn"
    )
    conv = [qa(1, "I like games"), qa(2, "I don't know")]
    plan = plan_question(3, 7, TRACK_LIST, conv)
    return build_turn_messages(
        prompt,
        settings,
        tracks=TRACK_LIST,
        grade=8,
        conversation=conv,
        question_number=3,
        max_questions=7,
        plan=plan,
        **kw,
    )


def test_dont_know_hint_asks_for_an_easier_different_question():
    user = _turn_prompt(dont_know=True)[1]["content"]
    assert "do not know" in user and "easier" in user and "Do NOT ask it again" in user
    assert "no new answer to judge" not in user


def test_prompts_target_beginners_aged_12_to_18_and_accept_dont_know():
    from pathlib import Path

    for name in ("discovery_turn@v1.md", "discovery_turn@v2.md"):
        text = Path("prompts", name).read_text(encoding="utf-8")
        assert "12 to 18" in text and "BEGINNERS" in text and "HOW THE STUDENT THINKS" in text
        assert "is NOT a bad answer" in text


def test_every_track_has_an_everyday_thinking_scenario():
    for t in TRACK_LIST:
        assert any(p.startswith("Thinking:") for p in probes_for(t)), t.code
