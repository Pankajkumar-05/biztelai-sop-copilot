"""Send the labelled questions to a RUNNING copilot and record what it actually answers.

    uvicorn app.main:app --host 0.0.0.0 --port 8000        (in another terminal)
    python scripts/run_questions.py                        (sample + original questions)
    python scripts/run_questions.py --group sample --group original --group extra
    python scripts/run_questions.py --url http://192.168.1.23:8000

Writes results/answers.json (full responses) and results/answers.md (a table to paste into the README).
Re-run it after setting an LLM key in .env so the README shows generated answers, not just evidence.
"""
import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def key_evidence(body: dict, facts: list[str]) -> str:
    """Evidence-only mode: quote the retrieved text around each key fact, so the README shows what the app really found."""
    if body["status"] != "evidence_only" or not facts:
        return "-"
    quotes = []
    for fact in facts[:2]:
        for source in body["sources"]:
            flat = " ".join(source["evidence"].split())
            pos = flat.find(fact)
            if pos != -1:
                excerpt = flat[max(0, pos - 50): pos + len(fact) + 90].replace("|", "/")
                label = f"{source['doc_no']} {source['revision_label']} p.{source['page']} sec {source['section'].split('.')[0]}"
                quotes.append(f"...{excerpt}... ({label})")
                break
        else:
            quotes.append(f"(fact {fact!r} not in the passages shown)")
    return " ".join(quotes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--group", action="append", help="sample / original / extra / tuning (repeatable)")
    args = parser.parse_args()
    groups = set(args.group or ["sample", "original"])

    questions = [q for q in json.loads((ROOT / "tests" / "questions.json").read_text(encoding="utf-8")) if q["group"] in groups]
    health = httpx.get(f"{args.url}/api/health", timeout=10).json()
    mode = f"LLM provider: {health['llm_provider']}" if health["llm_configured"] else "no LLM configured (evidence-only mode)"
    print(f"Server: {args.url}  |  {mode}\n")

    records, lines = [], [f"_Mode when recorded: {mode}_\n", "| # | Question | Status | Answer / evidence shown | Key evidence found | Revision note |", "|---|---|---|---|---|---|"]
    for q in questions:
        started = time.perf_counter()
        reply = httpx.post(f"{args.url}/api/ask", json={"question": q["question"]}, timeout=60)
        seconds = time.perf_counter() - started
        body = reply.json()
        records.append({"id": q["id"], "question": q["question"], "http_status": reply.status_code,
                        "seconds": round(seconds, 2), "response": body})

        cited = [s for s in body.get("sources", []) if s["cited"]]
        if body["status"] == "answered":
            evidence = "; ".join(f"[{s['ref']}] {s['doc_no']} {s['revision_label']}, page {s['page']}, {s['section'].split(' (')[0]}" for s in cited)
        else:
            evidence = key_evidence(body, q.get("facts", []))
        if body["status"] == "answered":
            shown = body["answer"]
        elif body["status"] == "evidence_only":
            shown = f"(no generated answer) {len(body['sources'])} passage(s) shown"
        else:
            shown = body["message"]
        note = "yes" if body.get("revision_note") else "-"
        print(f"{q['id']:3} {body['status']:13} {seconds:5.2f}s  {q['question'][:70]}")
        lines.append(f"| {q['id']} | {q['question']} | {body['status']} | {shown.replace(chr(10), ' ')} | {evidence} | {note} |")

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "answers.json").write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "results" / "answers.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nSaved results/answers.json and results/answers.md")


if __name__ == "__main__":
    main()
