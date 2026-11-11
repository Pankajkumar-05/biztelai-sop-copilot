"""The question -> answer pipeline, with a fake LLM so every branch can be tested."""
from app import copilot
from app.copilot import answer_question, ungrounded_numbers
from app.llm import LLMError
from conftest import FakeLLM, block_id

ALARM_Q = "The machine is showing alarm AL-104. What does it mean and what should the operator do?"
RPM_Q = "What is the maximum spindle speed (RPM) of the TX-200?"
LOT_Q = "For a 200-piece lot, how many samples are required?"
LOCK_Q = "Who is allowed to remove a lockout lock from a machine?"


def cite_the_alarm_block(_system, user):
    n = block_id(user, "Way lube oil level low")
    return f"According to the TX-200 manual, top up with ISO VG 68 oil to the MAX mark, then press RESET [C{n}]."


def test_answered_path_has_checked_citation_and_source(index):
    llm = FakeLLM(fn=cite_the_alarm_block)
    response = answer_question(ALARM_Q, index, llm)
    assert response.status == "answered" and response.llm_used
    assert "ISO VG 68" in response.answer and "[C" not in response.answer and "[" in response.answer
    cited = [s for s in response.sources if s.cited]
    assert len(cited) == 1
    source = cited[0]
    assert (source.doc_no, source.revision_label, source.section) == ("MNT-MAN-CNC-02", "Rev 02", "6. Common Alarms")
    assert source.page == "1-2" and source.revision_status == "newest_supplied"
    assert "TX-200" in source.scope and "Way lube oil level low" in source.evidence
    assert response.highlights and "al-104" in response.highlights


def test_the_llm_is_shown_the_strict_prompt_and_only_evidence(index):
    llm = FakeLLM(fn=cite_the_alarm_block)
    answer_question(ALARM_Q, index, llm)
    system, user = llm.calls[0]
    assert "Never use outside knowledge" in system and "NOT_FOUND" in system
    assert user.startswith("EVIDENCE") and "QUESTION" in user and "[C1]" in user
    assert "applies to:" in user


def test_unanswerable_question_never_calls_the_llm(index):
    llm = FakeLLM(reply="The maximum speed is 4000 RPM [C1].")
    response = answer_question(RPM_Q, index, llm)
    assert llm.calls == []
    assert response.status == "not_found" and response.sources == [] and response.answer == ""
    assert "couldn't find enough supporting information" in response.message
    assert "QMS" in response.message


def test_llm_saying_not_found_is_respected(index):
    response = answer_question(ALARM_Q, index, FakeLLM(reply="NOT_FOUND"))
    assert response.status == "not_found" and response.sources == [] and response.llm_used


def test_llm_asking_for_detail_is_respected(index):
    llm = FakeLLM(reply="NEEDS_DETAIL: Which machine is the alarm on?")
    response = answer_question(ALARM_Q, index, llm)
    assert response.status == "needs_detail" and "Which machine" in response.message


def test_vague_question_asks_for_detail_without_calling_the_llm(index):
    llm = FakeLLM(reply="x [C1]")
    response = answer_question("What is the tolerance?", index, llm)
    assert response.status == "needs_detail" and llm.calls == [] and response.sources == []


def test_answer_without_citation_is_not_shown(index):
    response = answer_question(ALARM_Q, index, FakeLLM(reply="Top up the oil and press RESET."))
    assert response.status == "evidence_only" and response.answer == ""
    assert "could not be tied to a source" in response.message and response.sources


def test_citation_to_a_block_that_does_not_exist_counts_as_uncited(index):
    response = answer_question(ALARM_Q, index, FakeLLM(reply="Top up the oil [C99]."))
    assert response.status == "evidence_only" and response.answer == ""


def test_number_not_in_the_evidence_blocks_the_answer(index):
    llm = FakeLLM(fn=lambda s, u: f"The torque is 999 Nm [C{block_id(u, 'criss-cross')}].")
    response = answer_question("What is the chuck mounting bolt torque?", index, llm)
    assert response.status == "evidence_only" and "999" in response.message and response.answer == ""


def test_correct_number_passes_the_check(index):
    llm = FakeLLM(fn=lambda s, u: f"Tighten the bolts to 110 Nm in a criss-cross sequence [C{block_id(u, 'criss-cross')}].")
    response = answer_question("What is the chuck mounting bolt torque?", index, llm)
    assert response.status == "answered" and "110 Nm" in response.answer


def test_ungrounded_numbers_helper(index):
    hits = index.search("What is the chuck mounting bolt torque?").current_hits
    q = "What is the chuck mounting bolt torque?"
    assert ungrounded_numbers("Use 110 Nm [C1].", hits, q) == []
    assert ungrounded_numbers("Use 120 Nm [C1].", hits, q) == ["120"]
    assert ungrounded_numbers("1. Isolate the machine\n2. Check the gauge", hits, q) == []   # list numbers ignored
    assert ungrounded_numbers("This is from Rev 02 of MNT-MAN-CNC-02 [C1].", hits, q) == []   # metadata numbers allowed


def test_llm_failure_still_exposes_the_evidence(index):
    response = answer_question(ALARM_Q, index, FakeLLM(error=LLMError("the answer service timed out")))
    assert response.status == "evidence_only" and not response.llm_used
    assert response.llm_error == "the answer service timed out"
    assert response.sources and response.sources[0].section.startswith("6. Common Alarms")
    assert "not available" in response.message


def test_no_llm_configured_still_shows_evidence(index):
    response = answer_question(ALARM_Q, index, llm=None)
    assert response.status == "evidence_only" and not response.llm_used and response.llm_error is None
    assert "No answer generator is configured" in response.message
    assert 1 <= len(response.sources) <= 6                      # retrieved passages, weak ones hidden
    assert response.sources[0].section.startswith("6. Common Alarms")
    assert response.safety_note is None                         # an alarm is not a safety-procedure question


def test_revision_note_for_a_revision_sensitive_question(index):
    response = answer_question(LOT_Q, index, llm=None)
    assert response.revision_note
    assert "Rev 03" in response.revision_note and "Rev 04" in response.revision_note
    assert "supersedes" in response.revision_note and "QMS" in response.revision_note
    assert "latest" not in response.revision_note.lower()       # we never claim 'latest in the QMS'
    qc = [s for s in response.sources if s.doc_no == "QC-SOP-014"]
    assert qc and all(s.revision == 4 and s.revision_status == "newest_supplied" for s in qc)


def test_no_revision_note_when_no_older_revision_matches(index):
    response = answer_question("What is the outer diameter tolerance for the BH-220 bearing housing?", index, llm=None)
    assert response.revision_note is None


def test_old_revision_text_never_reaches_the_llm(index):
    llm = FakeLLM(fn=lambda s, u: f"Draw 13 samples for lots of 91 to 500 pieces [C{block_id(u, 'Samples to inspect')}].")
    response = answer_question(LOT_Q, index, llm)
    evidence = llm.calls[0][1].split("\n\nQUESTION\n")[0]
    # No block is labelled Rev 03 and no Rev-03-only wording is present. (Rev 04's own revision-history line
    # says "Supersedes Rev 03"; that is current-document text, so the words "Rev 03" may legitimately appear.)
    assert "QC-SOP-014 Rev 03 |" not in evidence
    assert "irrespective of lot size" not in evidence and "Red Bin" not in evidence
    assert "QC-SOP-014 Rev 04 |" in evidence
    assert response.status == "answered" and "13" in response.answer
    assert all(s.revision == 4 for s in response.sources if s.doc_no == "QC-SOP-014")


def test_old_revision_wording_is_answered_from_the_current_revision_with_a_note(index):
    llm = FakeLLM(fn=lambda s, u: f"Rejected material gets a RED tag and goes to Quarantine Cage Q1, Stores Bay 3 [C{block_id(u, 'Quarantine Cage Q1')}].")
    response = answer_question("Where is the Red Bin area near Gate 2?", index, llm)
    assert "Red Bin" not in llm.calls[0][1].split("\n\nQUESTION\n")[0]      # evidence only; the question may say it
    assert response.status == "answered" and "Cage Q1" in response.answer
    assert response.revision_note and "Rev 03" in response.revision_note
    assert all(s.revision == 4 for s in response.sources if s.doc_no == "QC-SOP-014")


def test_topic_found_only_in_a_superseded_revision_says_so(index):
    question = "How many samples must be drawn from every lot irrespective of lot size?"
    response = answer_question(question, index, llm=FakeLLM(reply="x [C1]"))
    assert response.status == "not_found" and response.sources == []
    assert "older, superseded revision" in response.message and "Rev 03" in response.message


def test_safety_answer_carries_a_caution_and_the_exception_clause(index):
    llm = FakeLLM(fn=lambda s, u: f"Only the person who applied a lock may remove it [C{block_id(u, 'Nobody may remove')}].")
    response = answer_question(LOCK_Q, index, llm)
    assert response.status == "answered"
    assert response.safety_note and "does not replace" in response.safety_note
    sections = {(s.section[:2], s.cited) for s in response.sources if s.doc_no == "SAF-SOP-003"}
    assert ("5.", True) in sections
    assert ("6.", False) in sections                           # the 'owner is absent' exception is still surfaced
    full_text = " ".join(" ".join(s.evidence.split()) for s in response.sources)
    assert "Production Manager and the Safety Officer must both authorise" in full_text


def test_non_safety_answer_has_no_safety_note(index):
    response = answer_question(ALARM_Q, index, FakeLLM(fn=cite_the_alarm_block))
    assert response.safety_note is None


def test_hose_replacement_surfaces_the_lockout_dependency(index):
    response = answer_question("How do I replace a hydraulic hose?", index, llm=None)
    shown = " ".join(" ".join(s.evidence.split()) for s in response.sources)
    assert "Isolate the machine as per SAF-SOP-003" in shown
    assert response.safety_note


def test_alarm_typed_without_hyphen_gives_the_same_source(index):
    a = answer_question("AL104 on the machine, what do I do?", index, llm=None)
    b = answer_question("AL-104 on the machine, what do I do?", index, llm=None)
    assert a.status == b.status == "evidence_only"
    assert a.sources[0].section == b.sources[0].section == "6. Common Alarms"


def test_not_found_never_carries_a_revision_note(index):
    for question in ("What is the weather in Hosur today?", RPM_Q, "What is the canteen menu on Friday?"):
        response = answer_question(question, index, llm=None)
        assert response.status == "not_found" and response.revision_note is None, question
    llm_says_no = answer_question(LOT_Q, index, FakeLLM(reply="NOT_FOUND"))
    assert llm_says_no.status == "not_found" and llm_says_no.revision_note is None


# --- Answerability: the documents must contain what the question asks for -----------------------------------

def test_part_number_question_is_not_found_and_never_reaches_the_llm(index):
    # "pump" appears in none of the documents; "hydraulic", "part" and "number" do appear elsewhere.
    for question in ("What is the hydraulic pump part number?",
                     "What is the part number of the hydraulic pump on the TX-200?",
                     "Who supplies the hydraulic pump?"):
        llm = FakeLLM(reply="The part number is HP-4471 [C1].")   # a model that WOULD invent one
        response = answer_question(question, index, llm)
        assert response.status == "not_found", question
        assert response.sources == [] and "HP-4471" not in response.message
        assert llm.calls == []


def test_different_wordings_of_the_coolant_question_find_the_same_evidence(index):
    for question in ("What is the coolant mix percentage?", "What is the coolant concentration?",
                     "What percentage coolant should be used?", "Recommended coolant mixture?"):
        response = answer_question(question, index, None)
        assert response.status == "evidence_only", question
        assert any("6 - 8 %" in s.evidence for s in response.sources), question
        assert all(s.revision_status == "newest_supplied" for s in response.sources)


def test_unknown_word_is_reported_by_retrieval(index):
    assert "pump" in index.search("What is the hydraulic pump part number?").unknown_terms
    assert index.search("What is the coolant concentration?").unknown_terms == []
