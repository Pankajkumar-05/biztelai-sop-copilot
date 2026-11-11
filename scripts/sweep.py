"""Retrieval-only threshold sweep (no LLM, no cost).

For every labelled question in tests/questions.json prints: best score, coverage, whether the gate passes,
and where the expected sections rank among the current chunks. Use it to validate MIN_TOP_SCORE / MIN_COVERAGE
and TOP_K after any change to chunking or the analyzer.

    python scripts/sweep.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.ingest import load_corpus  # noqa: E402
from app.retrieval import Index  # noqa: E402


def main() -> int:
    corpus = load_corpus(config.PDF_DIR)
    index = Index(corpus)
    questions = json.loads((ROOT / "tests" / "questions.json").read_text(encoding="utf-8"))

    print(f"chunks: {len(corpus.chunks)} total, {len(index.current)} current, {len(index.superseded)} superseded")
    print(f"gate: score >= {config.MIN_TOP_SCORE}, coverage >= {config.MIN_COVERAGE}, top_k = {config.TOP_K}\n")
    print(f"{'id':4} {'ans':3} {'score':>6} {'cov':>5} {'gate':5} {'vague':5} {'old':3}  expected-section ranks   question")

    problems = []
    for q in questions:
        result = index.search(q["question"], top_k=len(index.current))  # full ranking so ranks can be shown
        passed = index.passes_gate(result)
        ranks = []
        for doc_no, rev, prefix in q["expected_sections"]:
            rank = next(
                (n for n, h in enumerate(result.current_hits, 1)
                 if h.chunk.doc_no == doc_no and h.chunk.revision == rev and h.chunk.section.startswith(prefix)),
                None,
            )
            ranks.append(rank)
        print(
            f"{q['id']:4} {'yes' if q['answerable'] else 'no':3} {result.top_score:6.3f} {result.coverage:5.2f} "
            f"{'pass' if passed else 'BLOCK':5} {'yes' if result.is_vague else '-':5} {len(result.superseded_hits):3}  "
            f"{str(ranks):24}  {q['question'][:60]}"
        )
        known = q.get("known_limitation")
        if known:
            print(f"     known limitation ({q['id']}): {known}")
        elif q["answerable"] and not passed:
            problems.append(f"{q['id']}: answerable question is BLOCKED by the gate")
        if q["answerable"] and not known and any(r is None or r > config.TOP_K for r in ranks):
            problems.append(f"{q['id']}: expected section not in top {config.TOP_K}: ranks {ranks}")
        if not q["answerable"] and passed:
            print(f"     note: {q['id']} is unanswerable but passes the gate (the LLM layer must say NOT_FOUND)")

    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print("No answerable question is blocked and every expected section is in the top-k.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
