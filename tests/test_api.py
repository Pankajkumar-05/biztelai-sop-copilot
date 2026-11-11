"""HTTP-level tests: routes, validation, error shapes."""
import app.main
from conftest import FakeLLM, block_id


def ask(client, **payload):
    return client.post("/api/ask", json=payload)


def test_health_lists_documents_and_mode(make_client):
    data = make_client().get("/api/health").json()
    assert data["status"] == "ok" and data["chunks"] == 32 and data["llm_configured"] is False
    qc = [d for d in data["documents"] if d["doc_no"] == "QC-SOP-014"][0]
    assert qc["revisions"] == [3, 4] and qc["newest_supplied"] == 4


def test_home_page_and_static_files_are_served(make_client):
    client = make_client()
    page = client.get("/")
    assert page.status_code == 200 and "SOP Copilot" in page.text and 'name="viewport"' in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_ask_returns_the_documented_shape(make_client):
    body = ask(make_client(), question="What is the chuck mounting bolt torque?").json()
    assert set(body) == {"status", "answer", "message", "sources", "revision_note", "safety_note",
                         "llm_used", "llm_error", "highlights"}
    source = body["sources"][0]
    assert {"ref", "cited", "doc_no", "title", "filename", "revision", "revision_label", "revision_status",
            "effective_date", "page", "section", "scope", "evidence", "safety_critical"} <= set(source)
    assert "110 Nm" in source["evidence"]


def test_ask_with_a_working_llm_end_to_end(make_client):
    llm = FakeLLM(fn=lambda s, u: f"Tighten to 110 Nm in a criss-cross sequence [C{block_id(u, 'criss-cross')}].")
    body = ask(make_client(llm), question="What is the chuck mounting bolt torque?").json()
    assert body["status"] == "answered" and "110 Nm" in body["answer"] and body["llm_used"] is True


def test_unanswerable_question_is_a_normal_200_not_found(make_client):
    response = ask(make_client(), question="What is the maximum spindle speed (RPM) of the TX-200?")
    assert response.status_code == 200 and response.json()["status"] == "not_found"


def test_empty_and_whitespace_questions_are_rejected(make_client):
    client = make_client()
    for text in ("", "   ", "\n\t"):
        response = ask(client, question=text)
        assert response.status_code == 422
        assert response.json() == {"status": "error", "message": "Please type a question."}


def test_overlong_question_is_rejected(make_client):
    response = ask(make_client(), question="a" * 501)
    assert response.status_code == 422 and "under 500 characters" in response.json()["message"]


def test_question_at_the_limit_is_accepted(make_client):
    assert ask(make_client(), question="coolant concentration " + "x " * 235).status_code == 200


def test_malformed_requests_get_a_friendly_422(make_client):
    client = make_client()
    missing = client.post("/api/ask", json={})
    wrong_type = client.post("/api/ask", json={"question": 42})
    not_json = client.post("/api/ask", content="not json", headers={"content-type": "application/json"})
    for response in (missing, wrong_type, not_json):
        assert response.status_code == 422
        assert response.json()["status"] == "error" and response.json()["message"]
    assert "question" in missing.json()["message"]


def test_question_with_irrelevant_text_still_finds_the_right_source(make_client):
    noise = "Today the shift started late because the bus was delayed and the canteen was closed. "
    body = ask(make_client(), question=noise + "Anyway, what does alarm AL-104 mean on the TX-200?").json()
    assert body["status"] in ("evidence_only", "not_found")
    if body["status"] == "evidence_only":
        assert body["sources"][0]["section"].startswith("6. Common Alarms")


def test_unexpected_error_returns_clean_json_500(make_client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(app.main, "answer_question", boom)
    response = ask(make_client(), question="What is the chuck mounting bolt torque?")
    assert response.status_code == 500
    assert response.json() == {"status": "error", "message": "Something went wrong while answering. Please try again."}
    assert "secret" not in response.text


def test_llm_outage_is_not_a_500(make_client):
    from app.llm import LLMError
    response = ask(make_client(FakeLLM(error=LLMError("the answer service timed out"))),
                   question="What is the chuck mounting bolt torque?")
    body = response.json()
    assert response.status_code == 200 and body["status"] == "evidence_only"
    assert body["llm_error"] and body["sources"]


def test_ask_is_post_only(make_client):
    assert make_client().get("/api/ask").status_code == 405
