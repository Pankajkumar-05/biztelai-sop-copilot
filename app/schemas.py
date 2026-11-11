from typing import Literal

from pydantic import BaseModel, field_validator

from . import config


class AskRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def check_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please type a question.")
        if len(value) > config.MAX_QUESTION_CHARS:
            raise ValueError(f"Please keep the question under {config.MAX_QUESTION_CHARS} characters.")
        return value


class Source(BaseModel):
    ref: int                      # matches the [n] markers in the answer
    cited: bool                   # False = shown as "also check" (same safety document), not cited by the answer
    doc_no: str
    title: str
    filename: str
    revision: int
    revision_label: str           # "Rev 04"
    revision_status: str          # "newest_supplied" | "superseded"
    effective_date: str
    page: str
    section: str
    scope: str                    # who/what the document applies to (e.g. "TX-200 ... machines CNC-04 to CNC-09")
    evidence: str                 # the exact text of the section
    safety_critical: bool


class AskResponse(BaseModel):
    # answered      = LLM answer that passed the citation / number checks
    # evidence_only = relevant passages shown without a generated answer (no LLM, LLM failed, or answer failed checks)
    # not_found     = not enough supporting information in the documents
    # needs_detail  = question too general to search
    # error         = unexpected application error
    status: Literal["answered", "evidence_only", "not_found", "needs_detail", "error"]
    answer: str = ""
    message: str = ""
    sources: list[Source] = []
    revision_note: str | None = None
    safety_note: str | None = None
    llm_used: bool = False
    llm_error: str | None = None
    highlights: list[str] = []    # question words (stemmed) the UI highlights inside the evidence text
