import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.ingest import load_corpus  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval import Index  # noqa: E402


@pytest.fixture(scope="session")
def corpus():
    return load_corpus(config.PDF_DIR)


@pytest.fixture(scope="session")
def index(corpus):
    return Index(corpus)


@pytest.fixture(scope="session")
def questions():
    return json.loads((ROOT / "tests" / "questions.json").read_text(encoding="utf-8"))


class FakeLLM:
    """Stands in for a real provider. Records every call so tests can check what the model was shown."""

    name = "fake"

    def __init__(self, reply=None, error=None, fn=None):
        self.reply, self.error, self.fn = reply, error, fn
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.fn(system, user) if self.fn else self.reply


def block_id(user_message: str, needle: str) -> int:
    """Number n of the evidence block [Cn] that contains `needle` (the question part is ignored)."""
    evidence = user_message.split("\n\nQUESTION\n")[0]
    for part in evidence.split("\n\n"):
        match = re.match(r"(?:EVIDENCE\n)?\[C(\d+)\]", part)
        if match and needle in part:
            return int(match.group(1))
    raise AssertionError(f"no evidence block contains {needle!r}")


@pytest.fixture()
def make_client(corpus):
    def _make(llm=None, raise_server_exceptions=False):
        return TestClient(create_app(corpus, llm_client=llm), raise_server_exceptions=raise_server_exceptions)
    return _make
