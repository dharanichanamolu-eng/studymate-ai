import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import study_logic as sl  # noqa: E402
from llm_service import personalize  # noqa: E402

EXAMPLE = "I studied Python loops today. I understand for loops, but nested loops are difficult for me."


def test_parse_example():
    p = sl.parse_study_input(EXAMPLE)
    assert p["subject"] == "Python"
    assert p["understood"] == ["for loops"]
    assert p["difficult"] == [("nested loops", 4)]
    assert p["studied"] == ["loops"]


def test_difficulty_intensifier():
    p = sl.parse_study_input("I studied Python. Recursion is very confusing.")
    assert p["difficult"] == [("recursion", 5)]


def test_struggle_phrase():
    p = sl.parse_study_input("I studied calculus. I struggle with integration by parts.")
    assert p["subject"] == "Calculus" and p["difficult"][0][0] == "integration by parts"


def test_not_study_text():
    assert sl.parse_study_input("hello there") is None


def test_intents():
    assert sl.detect_intent("What should I study next?") == "recommend"
    assert sl.detect_intent("show my history") == "memory"
    assert sl.detect_intent(EXAMPLE) == "record"


def test_recommendation_uses_retrieved_weak_topic():
    weak = [{"topic": "nested loops", "subject": "Python", "difficulty": 4, "reports": 2, "last_reported": "x"}]
    rec = sl.build_recommendation(weak, [], [], {"nested loops": ["for loops"]})
    assert rec["topic"] == "nested loops" and "for loops" in rec["reason"]
    assert len(rec["questions"]) == 5


def test_recommendation_prefers_hardest_first():
    weak = [{"topic": "recursion", "subject": "Python", "difficulty": 5, "reports": 1, "last_reported": "x"},
            {"topic": "nested loops", "subject": "Python", "difficulty": 4, "reports": 3, "last_reported": "x"}]
    assert sl.build_recommendation(weak, [], [])["topic"] == "recursion"


def test_no_history_returns_none():
    assert sl.build_recommendation([], [], []) is None


def test_fallback_is_labelled_when_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rec = sl._plan("nested loops", "Python", "reason", "weak")
    text, src = personalize(rec, [], [])
    assert "fallback" in src.lower() and "nested loops" in text.lower()


# ---- graph integration: runs only if a FalkorDB server is reachable ----
def _store():
    from graph_db import GraphStore
    s = GraphStore(graph_name="studymate_test")
    s.ping()
    return s


def test_graph_roundtrip_and_isolation():
    try:
        s = _store()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    s.ensure_schema()
    for sid in ("t-a", "t-b"):
        s.clear_student(sid)
    s.save_session("t-a", sl.parse_study_input(EXAMPLE), EXAMPLE)
    assert s.weak_topics("t-a")[0]["topic"] == "nested loops"
    assert s.weak_topics("t-b") == []
    assert s.related_understood("t-a", "Python", "nested loops") == ["for loops"]
    s.save_session("t-a", sl.parse_study_input("I understand nested loops now. I studied Python."), "x")
    assert s.weak_topics("t-a") == []
    s.clear_student("t-a")
