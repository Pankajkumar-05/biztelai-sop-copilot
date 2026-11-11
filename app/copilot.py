"""The question -> answer pipeline.

question -> retrieval -> revision filter -> not-found gate -> (LLM) -> citation/number checks -> response

Deterministic code makes the important decisions (what is evidence, what is not found, which revision, what is
shown). The LLM only turns the selected evidence into a short answer, and its output is checked afterwards.
"""
import logging
import re

from . import config
from .ingest import Corpus
from .llm import LLMClient, LLMError
from .prompt import SYSTEM_PROMPT, build_user_message
from .retrieval import Hit, Index
from .schemas import AskResponse, Source

log = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = (
    "I couldn't find enough supporting information for this question in the provided documents. "
    "Please check the QMS or the controlled manual, or contact the responsible team (maintenance, QC or safety)."
)
NEEDS_DETAIL_MESSAGE = (
    "Your question is too general to search reliably. Please add the machine, part or document it is about "
    "(for example: the dimension and the part name)."
)
NO_LLM_MESSAGE = (
    "No answer generator is configured, so this shows the most relevant passages from the documents. "
    "Read the passage below to find the answer."
)
SAFETY_NOTE = (
    "This involves a safety procedure (isolation / lockout). Read the full source text below and follow the "
    "original SOP. This app is a lookup aid and does not replace it."
)

CITATION_RE = re.compile(r"\[C(\d+)\]")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _make_source(ref: int, hit: Hit, cited: bool) -> Source:
    c = hit.chunk
    return Source(
        ref=ref, cited=cited, doc_no=c.doc_no, title=c.title, filename=c.filename, revision=c.revision,
        revision_label=c.revision_label,
        revision_status="newest_supplied" if c.status == "current" else "superseded",
        effective_date=c.effective_date, page=c.page_label, section=c.section, scope=c.scope,
        evidence=c.text, safety_critical=c.safety_critical,
    )


def _revision_note(corpus: Corpus, superseded_hits: list[Hit]) -> str | None:
    """Deterministic text (not written by the LLM) telling the user an older revision also matched."""
    if not superseded_hits:
        return None
    old = superseded_hits[0].chunk
    info = corpus.documents[old.doc_no]
    newest = info["current"]
    says_supersedes = info["declared_supersedes"].get(newest) == old.revision
    return (
        f"An older revision of {old.doc_no} (Rev {old.revision:02d}) also covers this topic. "
        f"Rev {newest:02d} is the newest revision in the documents supplied to this copilot"
        f"{f' and states that it supersedes Rev {old.revision:02d}' if says_supersedes else ''}, "
        f"so Rev {old.revision:02d} was not used. Confirm the current revision in the QMS."
    )


def ungrounded_numbers(answer: str, hits: list[Hit], question: str) -> list[str]:
    """Numbers in the answer that appear nowhere in the evidence that was sent (or the question)."""
    text = CITATION_RE.sub("", answer)
    text = "\n".join(re.sub(r"^\s*\d+[.)]\s+", "", line) for line in text.splitlines())  # ignore list numbering
    allowed = set(NUMBER_RE.findall(question))
    for hit in hits:
        c = hit.chunk
        allowed |= set(NUMBER_RE.findall(f"{c.doc_no} {c.revision_label} {c.page_label} {c.section} {c.effective_date} {c.text}"))
    return sorted(set(NUMBER_RE.findall(text)) - allowed)


def _shown_for_evidence_only(hits: list[Hit]) -> list[tuple[int, Hit, bool]]:
    """Without a generated answer, show the retrieved passages that are not far weaker than the best one.

    Not just the top 1-3: the passage holding the answer can rank 4th (e.g. the coolant table), so the cut-off
    is relative to the best score instead of a fixed count.
    """
    floor = config.EVIDENCE_ONLY_MIN_RELATIVE_SCORE * hits[0].score
    return [(i, h, False) for i, h in enumerate(hits, start=1) if h.score >= floor]


def _response(status, shown, *, terms=(), answer="", message="", note=None, llm_used=False, llm_error=None) -> AskResponse:
    sources = [_make_source(ref, hit, cited) for ref, hit, cited in shown]
    # With a generated answer, every shown source is tied to it. Without one, only the best passage decides,
    # so an alarm question is not labelled "safety" just because a lockout passage ranked 5th.
    basis = sources[:1] if status == "evidence_only" else sources
    safety = SAFETY_NOTE if any(s.safety_critical for s in basis) else None
    return AskResponse(
        status=status, answer=answer, message=message, sources=sources, revision_note=note,
        safety_note=safety, llm_used=llm_used, llm_error=llm_error,
        highlights=[t for t in terms if len(t) >= 3],
    )


def answer_question(question: str, index: Index, llm: LLMClient | None) -> AskResponse:
    result = index.search(question)
    note = _revision_note(index.corpus, result.older_versions)

    # 1. Too general to search.
    if result.is_vague:
        return AskResponse(status="needs_detail", message=NEEDS_DETAIL_MESSAGE)

    # 2. Not-found gate, before any LLM call.
    if not index.passes_gate(result):
        # No revision note here: nothing is being answered. The only exception is the message below, for a topic
        # that appears ONLY in a superseded revision.
        message = NOT_FOUND_MESSAGE
        if result.superseded_hits:
            old = result.superseded_hits[0].chunk
            message = (
                "I couldn't find enough supporting information for this question in the newest supplied revision. "
                f"Only an older, superseded revision ({old.doc_no} Rev {old.revision:02d}) mentions this topic, "
                "and it was not used. Please check the QMS or contact the responsible team."
            )
        return AskResponse(status="not_found", message=message)

    hits = result.current_hits   # only CURRENT chunks can ever be evidence

    # 3. No LLM configured: still useful, show the evidence.
    if llm is None:
        return _response("evidence_only", _shown_for_evidence_only(hits), terms=result.query_terms,
                         message=NO_LLM_MESSAGE, note=note)

    # 4. LLM answer, then check it.
    try:
        raw = llm.generate(SYSTEM_PROMPT, build_user_message(question, hits))
    except LLMError as exc:
        log.warning("LLM call failed: %s", exc)
        return _response(
            "evidence_only", _shown_for_evidence_only(hits), terms=result.query_terms, note=note, llm_error=str(exc),
            message="The answer service is not available right now, so this shows the most relevant passages "
                    "from the documents. Read the passage below to find the answer.",
        )

    text = raw.strip()
    print("GEMINI RAW RESPONSE:", repr(text))
    if text.upper().startswith("NOT_FOUND"):
        return AskResponse(status="not_found", message=NOT_FOUND_MESSAGE, llm_used=True)
    if text.upper().startswith("NEEDS_DETAIL"):
        detail = text.split(":", 1)[1].strip() if ":" in text else ""
        return AskResponse(status="needs_detail", message=detail or NEEDS_DETAIL_MESSAGE, llm_used=True)

    cited_numbers = sorted({int(n) for n in CITATION_RE.findall(text) if 1 <= int(n) <= len(hits)})
    if not cited_numbers:
        # An answer that cannot be tied to a source is not shown.
        return _response(
            "evidence_only", _shown_for_evidence_only(hits), terms=result.query_terms, note=note, llm_used=True,
            message="A generated answer could not be tied to a source passage, so it is not shown. "
                    "These are the closest passages in the documents.",
        )

    bad_numbers = ungrounded_numbers(text, hits, question)
    if bad_numbers:
        return _response(
            "evidence_only", _shown_for_evidence_only(hits), terms=result.query_terms, note=note, llm_used=True,
            message="The generated answer contained a number that is not in the source text "
                    f"({', '.join(bad_numbers)}), so it is not shown. These are the closest passages in the documents.",
        )

    shown = [(n, hits[n - 1], True) for n in cited_numbers]
    # Safety: also surface other safety passages from the same document that were retrieved but not cited.
    safety_docs = {hits[n - 1].chunk.doc_no for n in cited_numbers if hits[n - 1].chunk.safety_critical}
    for number, hit in enumerate(hits, start=1):
        if number not in cited_numbers and hit.chunk.safety_critical and hit.chunk.doc_no in safety_docs:
            shown.append((number, hit, False))

    answer = CITATION_RE.sub(lambda m: f"[{m.group(1)}]", text)
    return _response("answered", shown, terms=result.query_terms, answer=answer, note=note, llm_used=True)
