"""Citations must be true: the quoted evidence really sits on the page, in the document and revision shown."""
import re

import pytest
from pypdf import PdfReader

from app import config


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _pdf_pages(filename: str) -> dict[int, str]:
    reader = PdfReader(config.PDF_DIR / filename)
    return {n: _squash(page.extract_text() or "") for n, page in enumerate(reader.pages, start=1)}


def _page_range(label: str) -> range:
    first, _, last = label.partition("-")
    return range(int(first), int(last or first) + 1)


def test_every_chunk_text_comes_from_the_pages_it_claims(corpus):
    cache = {}
    for chunk in corpus.chunks:
        pages = cache.setdefault(chunk.filename, _pdf_pages(chunk.filename))
        claimed = " ".join(pages[n] for n in _page_range(chunk.page_label))
        # Every 5-word run of the chunk must be in the text of the cited pages. (A run that straddles a page break
        # can be cut by the page footer/header, so up to 4 misses per page break are tolerated; a wrong page or document misses far more.)
        words = _squash(chunk.text).split()
        runs = [" ".join(words[i:i + 5]) for i in range(max(1, len(words) - 4))]
        missing = [r for r in runs if r not in claimed]
        breaks = len(_page_range(chunk.page_label)) - 1
        assert len(missing) <= 4 * breaks, f"{chunk.doc_no} Rev {chunk.revision} p.{chunk.page_label}: {missing[:3]}"


def test_chunk_revision_matches_the_file_header(corpus):
    for chunk in corpus.chunks:
        header = _pdf_pages(chunk.filename)[1]
        assert chunk.doc_no in header and f"Rev {chunk.revision:02d}" in header, chunk.filename


@pytest.mark.parametrize("question", [
    "What is the recommended coolant concentration for the TX-200 CNC turning centre?",
    "For a 200-piece lot, how many samples are required?",
    "Who is allowed to remove a lockout lock from a machine?",
])
def test_sources_shown_to_the_user_are_never_superseded(index, question):
    from app.copilot import answer_question
    response = answer_question(question, index, None)
    assert response.sources
    assert all(s.revision_status == "newest_supplied" for s in response.sources)
    assert not any(s.doc_no == "QC-SOP-014" and s.revision == 3 for s in response.sources)
