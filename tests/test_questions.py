"""Data-driven checks over tests/questions.json (the labelled question set also used by scripts/sweep.py)."""
import json
from pathlib import Path

import pytest

from app.copilot import answer_question

QUESTIONS = json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))


def _mark(q):
    # Known limitations are expected to fail today; they stay in the set so the weakness is visible.
    return [pytest.mark.xfail(reason=q["known_limitation"], strict=False)] if q.get("known_limitation") else []


PARAMS = [pytest.param(q, id=q["id"], marks=_mark(q)) for q in QUESTIONS]
ANSWERABLE = [pytest.param(q, id=q["id"], marks=_mark(q)) for q in QUESTIONS if q["answerable"]]
UNANSWERABLE = [pytest.param(q, id=q["id"], marks=_mark(q)) for q in QUESTIONS if not q["answerable"]]


@pytest.mark.parametrize("q", ANSWERABLE)
def test_answerable_question_passes_the_gate(index, q):
    assert index.passes_gate(index.search(q["question"]))


@pytest.mark.parametrize("q", UNANSWERABLE)
def test_unanswerable_question_is_blocked_by_the_gate(index, q):
    assert not index.passes_gate(index.search(q["question"]))


@pytest.mark.parametrize("q", ANSWERABLE)
def test_expected_sections_are_in_the_top_k(index, q):
    hits = index.search(q["question"]).current_hits
    for doc_no, revision, prefix in q["expected_sections"]:
        assert any(
            h.chunk.doc_no == doc_no and h.chunk.revision == revision and h.chunk.section.startswith(prefix)
            for h in hits
        ), f"{q['id']}: {doc_no} Rev {revision} section {prefix} not in top {len(hits)}"


@pytest.mark.parametrize("q", ANSWERABLE)
def test_required_facts_appear_in_the_evidence_shown(index, q):
    """Retrieval-only (no LLM): the passages shown to the user must contain the facts the answer needs."""
    response = answer_question(q["question"], index, llm=None)
    assert response.status == "evidence_only"
    shown = " ".join(" ".join(s.evidence.split()) for s in response.sources)
    for fact in q["facts"]:
        assert fact in shown, f"{q['id']}: {fact!r} missing from the evidence"


@pytest.mark.parametrize("q", UNANSWERABLE)
def test_unanswerable_question_returns_not_found_without_sources(index, q):
    response = answer_question(q["question"], index, llm=None)
    assert response.status == "not_found" and response.sources == [] and response.answer == ""


@pytest.mark.parametrize("q", [p for p in PARAMS if p.values[0].get("revision_note_expected")])
def test_revision_note_appears_for_revision_sensitive_questions(index, q):
    response = answer_question(q["question"], index, llm=None)
    assert response.revision_note and "Rev 03" in response.revision_note and "Rev 04" in response.revision_note
