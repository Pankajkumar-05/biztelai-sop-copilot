"""FastAPI app: serves the page and the /api endpoints. Glue only; the logic lives in copilot.py."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .copilot import answer_question
from .ingest import Corpus, load_corpus
from .llm import get_llm_client
from .retrieval import Index
from .schemas import AskRequest, AskResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sop-copilot")

_FROM_ENV = object()   # sentinel: "build the LLM client from environment settings"


def create_app(corpus: Corpus | None = None, llm_client=_FROM_ENV) -> FastAPI:
    corpus = corpus or load_corpus(config.PDF_DIR)
    index = Index(corpus)
    llm = get_llm_client() if llm_client is _FROM_ENV else llm_client
    log.info(
        "Loaded %d chunks (%d current, %d superseded) from %d documents; LLM: %s",
        len(corpus.chunks), len(index.current), len(index.superseded), len(corpus.documents),
        llm.name if llm else "none (evidence-only mode)",
    )

    app = FastAPI(title="SOP Copilot")
    app.state.index, app.state.llm = index, llm

    @app.post("/api/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        response = answer_question(request.question, index, llm)
        log.info("ask -> %s", response.status)      # the question text itself is not logged
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "chunks": len(corpus.chunks),
            "llm_configured": llm is not None,
            "llm_provider": llm.name if llm else "none",
            "warnings": corpus.warnings,
            "documents": [
                {"doc_no": doc_no, "title": info["title"], "revisions": info["revisions"], "newest_supplied": info["current"]}
                for doc_no, info in sorted(corpus.documents.items())
            ],
        }

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError):
        # Friendly one-line message for the UI; no internals.
        first = exc.errors()[0] if exc.errors() else {}
        message = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
        if first.get("type") in ("missing", "json_invalid"):
            message = "Please send a JSON body like {\"question\": \"...\"}."
        return JSONResponse(status_code=422, content={"status": "error", "message": message})

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("Unexpected error")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Something went wrong while answering. Please try again."},
        )

    @app.get("/")
    def home() -> FileResponse:
        return FileResponse(config.STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
    return app


app = create_app()
