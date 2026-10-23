import pytest

from tests.conftest import b64, turn_body


def test_first_turn_returns_fixed_opening_with_audio(client):
    r = client.post("/v1/discovery/turns", json=turn_body())
    assert r.status_code == 200
    data = r.json()
    assert data["finished"] is False and data["answered"] is None
    q = data["next_question"]
    assert q["order_index"] == 1 and q["question_text"]
    assert q["audio_base64"] and q["audio_mime_type"] == "audio/wav"
    assert data["meta"]["model_id"] == "fixed"
    assert r.headers["x-request-id"]


def test_text_answer_returns_next_question(client):
    answer = {"order_index": 1, "question_text": "What do you enjoy?", "transcript": "I like drawing."}
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    data = r.json()
    assert r.status_code == 200
    assert data["answered"] == {"order_index": 1, "transcript": "I like drawing."}
    assert data["next_question"]["order_index"] == 2
    assert data["meta"]["prompt_version"] == "discovery_turn@v2"


def test_audio_answer_is_transcribed(client):
    answer = {
        "order_index": 1,
        "question_text": "What do you enjoy?",
        "audio_base64": b64(b"TEXT:I like robots"),
        "audio_mime_type": "audio/webm;codecs=opus",
    }
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    assert r.status_code == 200
    assert r.json()["answered"]["transcript"] == "I like robots"


def test_speak_false_returns_no_audio(client):
    r = client.post("/v1/discovery/turns", json=turn_body(speak=False))
    q = r.json()["next_question"]
    assert q["audio_base64"] is None and q["audio_mime_type"] is None


def test_last_answer_finishes_interview(client):
    history = [{"order_index": i, "question_text": f"Q{i}?", "transcript": "answer"} for i in range(1, 5)]
    answer = {"order_index": 5, "question_text": "Q5?", "transcript": "last one"}
    r = client.post("/v1/discovery/turns", json=turn_body(history=history, answer=answer, max_questions=5))
    data = r.json()
    assert data["finished"] is True and data["next_question"] is None
    assert data["answered"]["transcript"] == "last one"


def test_silent_audio_is_not_accepted_and_the_question_is_asked_again(client):
    answer = {
        "order_index": 2,
        "question_text": "ما المواد التي تحبها؟",
        "audio_base64": b64(b"TEXT:Thank you."),
        "audio_mime_type": "audio/wav",
    }
    history = [{"order_index": 1, "question_text": "Q1?", "transcript": "I like games"}]
    r = client.post("/v1/discovery/turns", json=turn_body(history=history, answer=answer))
    assert r.status_code == 200
    data = r.json()
    assert data["answer_status"] == "no_answer" and data["retry"] is True
    assert data["answered"] is None and data["finished"] is False
    q = data["next_question"]
    assert q["order_index"] == 2 and q["question_text"] == "ما المواد التي تحبها؟"
    assert q["nudge_text"] and q["audio_base64"]
    assert data["attempt"] == 2 and data["meta"]["model_id"] == "fixed"


def test_missing_answer_content_counts_as_no_answer(client):
    answer = {"order_index": 1, "question_text": "What do you enjoy?"}
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    data = r.json()
    assert r.status_code == 200 and data["answer_status"] == "no_answer" and data["retry"] is True
    assert data["next_question"]["order_index"] == 1


@pytest.mark.parametrize("text", ["امم", "umm"])
def test_fillers_are_not_accepted(client, text):
    answer = {"order_index": 1, "question_text": "What do you enjoy?", "transcript": text}
    data = client.post("/v1/discovery/turns", json=turn_body(answer=answer)).json()
    assert data["answer_status"] == "no_answer" and data["answered"] is None
    assert data["next_question"]["order_index"] == 1 and data["heard"] == text


def test_off_topic_answer_is_judged_by_the_model_and_not_accepted(client):
    answer = {"order_index": 1, "question_text": "What do you enjoy?", "transcript": "OFFTOPIC the weather"}
    data = client.post("/v1/discovery/turns", json=turn_body(answer=answer)).json()
    assert data["answer_status"] == "off_topic" and data["retry"] is True
    assert data["answered"] is None and data["finished"] is False
    q = data["next_question"]
    assert q["order_index"] == 1 and q["question_text"] == "What do you enjoy?"
    assert q["nudge_text"] and q["audio_base64"]
    assert data["heard"] == "OFFTOPIC the weather"


def test_off_topic_last_answer_does_not_finish_the_interview(client):
    history = [{"order_index": i, "question_text": f"Q{i}?", "transcript": "answer"} for i in range(1, 5)]
    answer = {"order_index": 5, "question_text": "Q5?", "transcript": "OFFTOPIC"}
    r = client.post("/v1/discovery/turns", json=turn_body(history=history, answer=answer, max_questions=5))
    data = r.json()
    assert data["finished"] is False and data["answer_status"] == "off_topic"
    assert data["next_question"]["order_index"] == 5


def test_silent_last_answer_does_not_finish_the_interview(client):
    history = [{"order_index": i, "question_text": f"Q{i}?", "transcript": "answer"} for i in range(1, 5)]
    answer = {"order_index": 5, "question_text": "Q5?", "transcript": "umm"}
    data = client.post(
        "/v1/discovery/turns", json=turn_body(history=history, answer=answer, max_questions=5)
    ).json()
    assert data["finished"] is False and data["next_question"]["order_index"] == 5


def test_accepted_answer_resets_the_attempt_counter(client):
    answer = {
        "order_index": 1,
        "question_text": "What do you enjoy?",
        "transcript": "I like drawing.",
        "attempt": 3,
    }
    data = client.post("/v1/discovery/turns", json=turn_body(answer=answer)).json()
    assert data["answer_status"] == "accepted" and data["retry"] is False and data["attempt"] == 1
    assert data["next_question"]["nudge_text"] is None


def test_later_attempt_uses_the_gentler_nudge(client):
    answer = {"order_index": 1, "question_text": "Q?", "transcript": "umm"}
    first = client.post("/v1/discovery/turns", json=turn_body(answer=answer)).json()
    again = client.post(
        "/v1/discovery/turns", json=turn_body(answer={**answer, "transcript": "", "attempt": 2})
    ).json()
    assert first["next_question"]["nudge_text"] != again["next_question"]["nudge_text"]


def test_unsupported_audio_type_returns_415(client):
    answer = {
        "order_index": 1,
        "question_text": "Q?",
        "audio_base64": b64(b"abc"),
        "audio_mime_type": "audio/flac",
    }
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    assert r.status_code == 415 and r.json()["error"]["code"] == "AUDIO_UNSUPPORTED"


def test_audio_too_large_returns_413(client):
    big = b64(b"\x00" * (10 * 1024 * 1024 + 10))
    answer = {"order_index": 1, "question_text": "Q?", "audio_base64": big, "audio_mime_type": "audio/wav"}
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    assert r.status_code == 413 and r.json()["error"]["code"] == "AUDIO_TOO_LARGE"


def test_bad_base64_returns_400(client):
    answer = {
        "order_index": 1,
        "question_text": "Q?",
        "audio_base64": "!!!not-base64!!!",
        "audio_mime_type": "audio/wav",
    }
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_text_and_audio_together_is_invalid(client):
    answer = {
        "order_index": 1,
        "question_text": "Q?",
        "transcript": "hi",
        "audio_base64": b64(b"x"),
        "audio_mime_type": "audio/wav",
    }
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    assert r.status_code == 400


def test_validation_error_never_echoes_student_text(client):
    answer = {"order_index": 1, "question_text": "Q?", "transcript": "SECRET-ANSWER " * 200}
    r = client.post("/v1/discovery/turns", json=turn_body(answer=answer))
    assert r.status_code == 400
    assert "SECRET-ANSWER" not in r.text


async def test_opening_audio_is_retried_after_a_network_blip():
    from app.providers.base import SpeechAudio
    from app.providers.errors import ProviderServerError
    from app.providers.fake import FakeLlm, FakeStt
    from app.services.prompts import PromptStore
    from app.services.turn_service import TurnService
    from app.services.wav import silent_wav
    from tests.conftest import make_settings

    class FlakyTts:
        calls = 0

        async def speak(self, text):
            FlakyTts.calls += 1
            if FlakyTts.calls == 1:
                raise ProviderServerError("network")
            return SpeechAudio(silent_wav(), "audio/wav")

    s = make_settings()
    prompts = PromptStore(s.prompts_dir, {"discovery_turn": "v2", "discovery_result": "v2"})
    svc = TurnService(settings=s, llm=FakeLlm(), stt=FakeStt(), tts=FlakyTts(), prompts=prompts)
    await svc.warm_up(attempts=1)
    assert svc._opening_audio is not None and FlakyTts.calls == 2


@pytest.mark.parametrize("text", ["مش عارف", "معرفش والله", "I don't know", "idk"])
def test_dont_know_is_a_real_answer_and_the_interview_continues(client, text):
    history = [{"order_index": 1, "question_text": "Q1?", "transcript": "I like games"}]
    answer = {"order_index": 2, "question_text": "Q2?", "transcript": text}
    data = client.post("/v1/discovery/turns", json=turn_body(history=history, answer=answer)).json()
    assert data["answer_status"] == "accepted" and data["retry"] is False
    assert data["answered"] == {"order_index": 2, "transcript": text}
    assert data["finished"] is False and data["next_question"]["order_index"] == 3
    assert data["next_question"]["nudge_text"] is None


def test_dont_know_on_the_last_question_finishes_the_interview(client):
    history = [{"order_index": i, "question_text": f"Q{i}?", "transcript": "answer"} for i in range(1, 5)]
    answer = {"order_index": 5, "question_text": "Q5?", "transcript": "I don't know"}
    data = client.post(
        "/v1/discovery/turns", json=turn_body(history=history, answer=answer, max_questions=5)
    ).json()
    assert data["finished"] is True and data["answer_status"] == "accepted"
