from pypdf import PdfWriter

from app.ingest import load_corpus


def sections(corpus, doc_no, revision):
    return [c for c in corpus.chunks if c.doc_no == doc_no and c.revision == revision]


def test_four_pdfs_become_three_documents(corpus):
    assert set(corpus.documents) == {"MNT-MAN-CNC-02", "QC-SOP-014", "SAF-SOP-003"}
    assert corpus.documents["QC-SOP-014"]["revisions"] == [3, 4]
    assert corpus.warnings == []


def test_chunk_counts(corpus):
    current = [c for c in corpus.chunks if c.status == "current"]
    superseded = [c for c in corpus.chunks if c.status == "superseded"]
    assert (len(corpus.chunks), len(current), len(superseded)) == (32, 25, 7)


def test_every_chunk_has_core_metadata(corpus):
    for c in corpus.chunks:
        assert c.doc_no and c.title and c.filename and c.section and c.text
        assert c.revision >= 1 and c.page_label != "?" and c.effective_date
        assert c.revision_label == f"Rev {c.revision:02d}"


def test_chunk_ids_are_unique(corpus):
    ids = [c.chunk_id for c in corpus.chunks]
    assert len(ids) == len(set(ids))


def test_rev03_is_superseded_and_rev04_is_current(corpus):
    assert {c.status for c in sections(corpus, "QC-SOP-014", 3)} == {"superseded"}
    assert {c.superseded_by for c in sections(corpus, "QC-SOP-014", 3)} == {4}
    assert {c.status for c in sections(corpus, "QC-SOP-014", 4)} == {"current"}
    assert {c.superseded_by for c in sections(corpus, "QC-SOP-014", 4)} == {None}


def test_documents_with_one_revision_are_current(corpus):
    for doc_no in ("MNT-MAN-CNC-02", "SAF-SOP-003"):
        assert {c.status for c in corpus.chunks if c.doc_no == doc_no} == {"current"}


def test_declared_supersedes_is_recorded_and_agrees(corpus):
    assert corpus.documents["QC-SOP-014"]["declared_supersedes"] == {4: 3}
    assert corpus.documents["QC-SOP-014"]["current"] == 4


def test_revisions_are_never_merged(corpus):
    rev3 = " ".join(c.text for c in sections(corpus, "QC-SOP-014", 3))
    rev4 = " ".join(c.text for c in sections(corpus, "QC-SOP-014", 4))
    assert "irrespective of lot size" in rev3 and "irrespective of lot size" not in rev4
    assert "Red Bin" in rev3 and "Red Bin" not in rev4
    assert "Quarantine Cage Q1" in rev4 and "Quarantine Cage Q1" not in rev3


def test_procedure_steps_are_not_mistaken_for_headings(corpus):
    names = [c.section for c in sections(corpus, "QC-SOP-014", 4)]
    assert [n.split(".")[0] for n in names] == [str(i) for i in range(9)]   # 0 (cover) then 1..8


def test_wrapped_heading_is_joined(corpus):
    heading = [c.section for c in sections(corpus, "QC-SOP-014", 4) if c.section.startswith("6.")][0]
    assert heading == "6. Inspection Dimensions - BH-220 Bearing Housing (Machined, from sub-contractor)"


def test_page_labels_show_spans(corpus):
    by_section = {c.section[:2]: c for c in sections(corpus, "QC-SOP-014", 4)}
    assert by_section["5."].page_label == "1-2"      # heading on page 1, steps on page 2
    assert by_section["6."].page_label == "2"
    assert by_section["4."].page_label == "1"


def test_title_effective_date_and_cover_chunk(corpus):
    rev4 = sections(corpus, "QC-SOP-014", 4)[0]
    assert rev4.title == "Incoming Material Inspection - Standard Operating Procedure"
    assert rev4.effective_date == "01-Jul-2026"
    cover = [c for c in corpus.chunks if c.section == "0. Document control"]
    assert len(cover) == 4
    assert all(c.title not in c.text for c in cover)      # title is metadata, not searchable cover text
    assert any("Approved By" in c.text for c in cover)


def test_scope_sentence_names_the_machine_or_area(corpus):
    mnt = sections(corpus, "MNT-MAN-CNC-02", 2)[0]
    assert "TX-200" in mnt.scope and "CNC-04 to CNC-09" in mnt.scope
    assert "BH-220" in sections(corpus, "QC-SOP-014", 4)[0].scope
    assert "Hosur plant" in sections(corpus, "SAF-SOP-003", 5)[0].scope


def test_safety_flags(corpus):
    assert all(c.safety_critical for c in corpus.chunks if c.doc_no == "SAF-SOP-003" and c.section[0] in "456")
    hose = [c for c in corpus.chunks if c.section.startswith("7. Replacing a Hydraulic Hose")][0]
    assert hose.safety_critical
    alarms = [c for c in corpus.chunks if c.section.startswith("6. Common Alarms")][0]
    assert not alarms.safety_critical
    assert not any(c.safety_critical for c in corpus.chunks if c.doc_no == "QC-SOP-014")


def test_pdf_without_revision_header_is_skipped_with_warning(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(tmp_path / "blank.pdf", "wb") as handle:
        writer.write(handle)
    result = load_corpus(tmp_path)
    assert result.chunks == []
    assert any("blank.pdf" in w and "skipped" in w for w in result.warnings)
