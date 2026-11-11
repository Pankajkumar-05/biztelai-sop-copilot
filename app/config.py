"""Settings in one place, so thresholds are easy to find and tune."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PDF_DIR = BASE_DIR / "data" / "pdfs"
STATIC_DIR = BASE_DIR / "static"

# --- Retrieval ---------------------------------------------------------------
# How many of the best-matching CURRENT chunks are sent to the LLM / shown as evidence.
# 6 (not 5) because the section a question needs can rank 4th-5th (e.g. the coolant table, the lockout
# exception clause). scripts/sweep.py prints the real ranks.
TOP_K = 6

# In evidence-only mode (no generated answer), hide passages scoring below this share of the best passage's score.
# 0.30 hid the coolant table for sample question 1 (its score is ~0.30 of the best), so 0.25. Chosen on this small
# set; tests/test_questions.py checks that every answerable question still shows the facts it needs.
EVIDENCE_ONLY_MIN_RELATIVE_SCORE = 0.25

# --- "Not found" gate (checked BEFORE any LLM call) --------------------------
# top score must be at least this ...
MIN_TOP_SCORE = 0.08
# ... and at least this share of the question's meaningful words must appear in one of the 3 best chunks.
# Initial values chosen from a small sweep; re-run scripts/sweep.py after changing chunking.
MIN_COVERAGE = 0.40

# A question word that appears NOWHERE in the documents (e.g. "pump" in "hydraulic pump part number") means the
# documents may simply not talk about what is being asked. The question is then only answerable if the rest of it
# is covered very strongly (typos, small wording gaps). Below this coverage, an unknown word blocks the answer.
UNKNOWN_TERM_MIN_COVERAGE = 0.75

# --- Request limits ----------------------------------------------------------
MAX_QUESTION_CHARS = 500

# --- LLM ---------------------------------------------------------------------
LLM_TIMEOUT_SECONDS = 20.0
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"


def llm_settings() -> dict:
    """Read LLM settings at call time (so tests can change environment variables)."""
    return {
        "provider": os.getenv("LLM_PROVIDER", "none").strip().lower(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "base_url": os.getenv("LLM_BASE_URL", "").strip(),
    }
