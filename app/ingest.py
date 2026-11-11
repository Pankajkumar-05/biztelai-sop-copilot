"""PDF -> labelled chunks.

One chunk = one numbered section of one document, carrying the document number, title,
revision, page span, section name, scope sentence and a current/superseded status.
Two revisions of the same document are kept as two separate sets of chunks. They are never merged.
"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pypdf

log = logging.getLogger(__name__)

# "QC-SOP-014  |  Rev 04  |  Uncontrolled copy when printed. ..."
HEADER_RE = re.compile(r"^\s*([A-Z0-9]+(?:-[A-Z0-9]+)+)\s*\|\s*Rev\s*(\d+)\b")
PAGE_RE = re.compile(r"^\s*Page\s+\d+\s*$")
# Section headings have ONE space after the number ("4. Sampling Plan").
# Procedure steps are printed " 1.  text" (leading space, two spaces) so they do not match.
HEADING_RE = re.compile(r"^(\d+)\.\s(\S.*)$")
SUPERSEDES_RE = re.compile(r"Supersedes\s+Rev\s*(\d+)", re.IGNORECASE)

# Chunks mentioning these are flagged so the UI can show the full source text and a caution.
SAFETY_WORDS = (
    "lockout", "tagout", "loto", "isolat", "energi", "stored energy", "zero energy", "danger tag",
)

DOCUMENT_CONTROL = "0. Document control"


@dataclass
class Chunk:
    chunk_id: str
    filename: str
    doc_no: str
    title: str
    revision: int
    effective_date: str
    page_label: str
    section: str
    text: str
    scope: str
    safety_critical: bool
    status: str = "current"          # "current" or "superseded" (set after all files are read)
    superseded_by: int | None = None

    @property
    def revision_label(self) -> str:
        return f"Rev {self.revision:02d}"


@dataclass
class Corpus:
    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # doc_no -> {"title", "revisions": [..], "current": int, "declared_supersedes": {rev: older_rev}}
    documents: dict = field(default_factory=dict)

    def current_chunks(self) -> list[Chunk]:
        return [c for c in self.chunks if c.status == "current"]

    def superseded_chunks(self) -> list[Chunk]:
        return [c for c in self.chunks if c.status == "superseded"]


def _page_label(pages: set[int]) -> str:
    pages = sorted(pages)
    if not pages:
        return "?"
    return str(pages[0]) if pages[0] == pages[-1] else f"{pages[0]}-{pages[-1]}"


def _first_sentence(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    end = text.find(". ")
    sentence = text if end == -1 else text[: end + 1]
    return sentence[:limit].rstrip()


def _read_lines(pdf_path: Path):
    """Return (doc_no, revision, [(page_number, line), ...]) with repeated header/footer noise removed."""
    reader = pypdf.PdfReader(str(pdf_path))
    doc_no, revision = None, None
    lines = []
    company_line = None
    for page_number, page in enumerate(reader.pages, start=1):
        for raw in (page.extract_text() or "").splitlines():
            match = HEADER_RE.match(raw)
            if match:
                doc_no, revision = match.group(1), int(match.group(2))
                continue
            if PAGE_RE.match(raw) or not raw.strip():
                continue
            # The line right after "Page N" is the company name; it repeats on every page.
            if "Pvt. Ltd." in raw:
                company_line = raw.strip()
                continue
            lines.append((page_number, raw.rstrip()))
    return doc_no, revision, lines, company_line


def _split_sections(lines):
    """Split into [(heading, pages, [text lines])]. The text before section 1 is 'Document control'."""
    sections = []
    current = {"heading": DOCUMENT_CONTROL, "pages": set(), "lines": []}
    expected = 1
    i = 0
    while i < len(lines):
        page_number, line = lines[i]
        match = HEADING_RE.match(line)
        if match and int(match.group(1)) == expected:
            heading = line.strip()
            pages = {page_number}
            # A long heading can wrap onto the next line, e.g. "(Machined, from" / "sub-contractor)".
            while heading.count("(") > heading.count(")") and i + 1 < len(lines):
                i += 1
                heading += " " + lines[i][1].strip()
                pages.add(lines[i][0])
            sections.append(current)
            current = {"heading": heading, "pages": pages, "lines": [heading]}
            expected += 1
        else:
            current["pages"].add(page_number)
            current["lines"].append(line.strip())
        i += 1
    sections.append(current)
    return [s for s in sections if s["lines"]]


def _cover_value(cover_lines: list[str], label: str) -> str:
    for index, line in enumerate(cover_lines):
        if line.strip().lower() == label.lower() and index + 1 < len(cover_lines):
            return cover_lines[index + 1].strip()
    return ""


def load_corpus(pdf_dir: Path) -> Corpus:
    corpus = Corpus()
    declared: dict[str, dict[int, int]] = {}

    for pdf_path in sorted(Path(pdf_dir).glob("*.pdf")):
        doc_no, revision, lines, _ = _read_lines(pdf_path)
        if doc_no is None or revision is None:
            # Never guess a revision: a file with no readable header is skipped and reported.
            corpus.warnings.append(f"{pdf_path.name}: no 'DOC-NO | Rev NN' header found, file skipped")
            log.warning(corpus.warnings[-1])
            continue

        sections = _split_sections(lines)
        cover_lines = [l.strip() for l in sections[0]["lines"]] if sections[0]["heading"] == DOCUMENT_CONTROL else []
        title = cover_lines[0] if cover_lines else doc_no
        effective_date = _cover_value(cover_lines, "Effective Date")

        # Scope sentence: prefer a "Scope" section, else "Purpose" (the TX-200 manual names its machines there).
        scope = ""
        for wanted in ("scope", "purpose"):
            for s in sections:
                name = s["heading"].split(".", 1)[-1].strip().lower()
                if name == wanted:
                    scope = _first_sentence(" ".join(s["lines"][1:]))
                    break
            if scope:
                break

        full_text = " ".join(l for s in sections for l in s["lines"])
        found = SUPERSEDES_RE.search(full_text)
        if found:
            declared.setdefault(doc_no, {})[revision] = int(found.group(1))

        for s in sections:
            body_lines = s["lines"]
            # The title is stored as metadata. Keeping it out of the searchable cover text stops the cover
            # chunk from outranking real content just because a question mentions the machine name.
            if s["heading"] == DOCUMENT_CONTROL and body_lines and body_lines[0].strip() == title:
                body_lines = body_lines[1:]
            text = " ".join(body_lines)
            number = s["heading"].split(".", 1)[0]
            lowered = text.lower()
            corpus.chunks.append(
                Chunk(
                    chunk_id=f"{doc_no}_r{revision:02d}_s{number}",
                    filename=pdf_path.name,
                    doc_no=doc_no,
                    title=title,
                    revision=revision,
                    effective_date=effective_date,
                    page_label=_page_label(s["pages"]),
                    section=s["heading"],
                    text=text,
                    scope=scope,
                    safety_critical=any(word in lowered for word in SAFETY_WORDS),
                )
            )

    _flag_safety_documents(corpus)
    _mark_revisions(corpus, declared)
    return corpus


def _flag_safety_documents(corpus: Corpus) -> None:
    """If most sections of a document are about isolation/lockout, every section of it is safety-critical.

    Needed because the key rule in the LOTO SOP ("each person removes only their own lock") contains none of
    the keywords itself, yet it is exactly the text a supervisor must not see without the safety caution.
    """
    by_file: dict[str, list[Chunk]] = {}
    for chunk in corpus.chunks:
        by_file.setdefault(chunk.filename, []).append(chunk)
    for chunks in by_file.values():
        flagged = sum(c.safety_critical for c in chunks)
        if flagged / len(chunks) >= 0.5:
            for c in chunks:
                c.safety_critical = True


def _mark_revisions(corpus: Corpus, declared: dict) -> None:
    """Highest revision number per document is 'current' (meaning: newest SUPPLIED, not necessarily newest in the QMS)."""
    by_doc: dict[str, list[Chunk]] = {}
    for chunk in corpus.chunks:
        by_doc.setdefault(chunk.doc_no, []).append(chunk)

    for doc_no, chunks in by_doc.items():
        revisions = sorted({c.revision for c in chunks})
        newest = revisions[-1]
        for chunk in chunks:
            if chunk.revision == newest:
                chunk.status, chunk.superseded_by = "current", None
            else:
                chunk.status, chunk.superseded_by = "superseded", newest

        # Cross-check against what the document itself says ("Supersedes Rev 03").
        for rev, older in declared.get(doc_no, {}).items():
            lower = [r for r in revisions if r < rev]
            if lower and older != lower[-1]:
                corpus.warnings.append(
                    f"{doc_no} Rev {rev:02d} says it supersedes Rev {older:02d}, "
                    f"but the next older supplied revision is Rev {lower[-1]:02d}"
                )
                log.warning(corpus.warnings[-1])

        corpus.documents[doc_no] = {
            "title": chunks[0].title,
            "revisions": revisions,
            "current": newest,
            "declared_supersedes": declared.get(doc_no, {}),
        }
