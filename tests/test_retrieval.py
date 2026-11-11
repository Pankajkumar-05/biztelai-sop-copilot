import pytest

from app import config
from app.retrieval import stem


def top_sections(result, n=None):
    return [(h.chunk.doc_no, h.chunk.revision, h.chunk.section) for h in result.current_hits[:n]]


def test_stemming_groups_word_forms():
    assert stem("checked") == stem("checking") == stem("check")
    assert stem("centres") == stem("centre")
    assert stem("changed") == stem("change")
    assert stem("tolerances") == stem("tolerance")
    assert stem("al-104") == "al-104"        # codes are never stemmed


def test_code_without_hyphen_matches_code_with_hyphen(index):
    tokens = index.analyzer.tokens
    assert tokens("AL104") == tokens("AL-104") == tokens("al 104") == ["al-104"]
    assert tokens("BH220 housing")[0] == "bh-220"


def test_numbers_after_ordinary_words_are_not_glued(index):
    assert "200" in index.analyzer.tokens("a lot of 200 pieces")
    assert "of-200" not in index.analyzer.tokens("a lot of 200 pieces")


def test_hyphenated_words_are_split_but_codes_stay_whole(index):
    tokens = index.analyzer.tokens("a 200-piece lot, QC-SOP-014")
    assert "200" in tokens and "piec" in tokens
    assert "qc-sop-014" in tokens


@pytest.mark.parametrize("question", ["What does AL-104 mean?", "What does AL104 mean?", "what does al 104 mean"])
def test_alarm_code_finds_the_alarm_table_however_it_is_typed(index, question):
    result = index.search(question)
    best = result.current_hits[0].chunk
    assert best.section.startswith("6. Common Alarms")
    assert "Way lube oil level low" in best.text and "ISO VG 68" in best.text


def test_bh220_outer_diameter_comes_from_rev04_only(index):
    best = index.search("What is the outer diameter tolerance for the BH-220 bearing housing?").current_hits[0].chunk
    assert (best.doc_no, best.revision) == ("QC-SOP-014", 4)
    assert "Outer diameter 90.000 +/- 0.050" in best.text


def test_only_current_chunks_can_be_evidence(index, questions):
    for q in questions:
        result = index.search(q["question"])
        assert all(h.chunk.status == "current" for h in result.current_hits), q["id"]


def test_old_revision_match_is_reported_separately(index):
    result = index.search("For a 200-piece lot, how many samples are required?")
    assert result.older_versions and result.older_versions[0].chunk.revision == 3
    assert result.current_hits[0].chunk.revision == 4
    assert "13" in result.current_hits[0].chunk.text          # lot size 91-500 -> 13 samples (Rev 04)


def test_old_revision_wording_does_not_pull_old_text_into_evidence(index):
    result = index.search("Where is the Red Bin area near Gate 2?")
    assert all("Red Bin" not in h.chunk.text for h in result.current_hits)
    assert result.older_versions                               # but we still know Rev 03 mentions it


def test_lockout_question_retrieves_both_the_rule_and_the_exception(index):
    result = index.search("Who is allowed to remove a lockout lock from a machine?")
    found = {h.chunk.section[:2] for h in result.current_hits if h.chunk.doc_no == "SAF-SOP-003"}
    assert {"5.", "6."} <= found
    assert all(h.chunk.safety_critical for h in result.current_hits if h.chunk.doc_no == "SAF-SOP-003")


def test_vague_question_is_flagged(index):
    assert index.search("What is the tolerance?").is_vague
    assert not index.search("AL-104?").is_vague
    assert not index.search("coolant concentration").is_vague


@pytest.mark.parametrize("question", [
    "What is the canteen menu on Friday?",
    "What is the weather in Hosur today?",
    "What is the maximum spindle speed (RPM) of the TX-200?",
    "What is the torque for the spindle motor bearing on the TX-300?",
])
def test_gate_blocks_unrelated_questions(index, question):
    assert not index.passes_gate(index.search(question))


def test_gate_thresholds_are_the_documented_ones():
    assert (config.MIN_TOP_SCORE, config.MIN_COVERAGE, config.TOP_K) == (0.08, 0.40, 6)
