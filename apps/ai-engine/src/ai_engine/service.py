"""FastAPI entrypoint for the independently deployable AI engine.

Keep routers thin: request validation -> engine call -> response mapping.
Retrieval/guardrail logic belongs in sibling modules of this package, which must
stay importable without FastAPI so the eval harness can call them directly.

Contract: packages/contracts/openapi.yaml, `generation` 태그 (ADR-0006). Only
apps/backend calls this service, and it never calls back — see the app-boundary rule in
AGENTS.md.

⚠️ Retrieval is deliberately **not** an endpoint. It is a stage inside the one-way
pipeline (parsing → chunking → embedding → retrieval → generation); exposing it would
invite callers into the middle of that pipeline. The eval harness reaches it by importing
`ai_engine.retrieval` directly, which is exactly why the module stays FastAPI-free.

⚠️ These paths must not be exposed publicly in deployment — they take a vulnerability
profile and carry no authentication of their own.
"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from ai_engine.config import get_settings
from ai_engine.generation import (
    GenerationFailedError,
    Generator,
    StubGenerator,
    answer_question,
    generate_message,
)
from ai_engine.models import (
    AnswerRequest,
    AnswerResponse,
    GenerationRequest,
    GenerationResponse,
)
from ai_engine.retrieval import ChromaRetriever, FixtureRetriever, Retriever

app = FastAPI(title="savers-ai-engine")


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """Process-wide retriever.

    Cached because reloading the corpus per request would land directly in the ≤30s
    end-to-end budget. Tests call the generation functions directly with their own
    retriever instead of poking at this cache.

    Backend picked by `Settings.retriever_backend` (default `fixture`) — see
    `ai_engine.config` for why the default cannot be `chroma` yet.
    """
    if get_settings().retriever_backend == "chroma":
        return ChromaRetriever.from_persist_dir()
    return FixtureRetriever.from_jsonl()


@lru_cache(maxsize=1)
def get_generator() -> Generator:
    """Process-wide generator.

    Returns the offline stub until a HyperCLOVA X client exists. Keeping the swap behind
    one function is what stops model-client details from leaking into the routers.
    """
    return StubGenerator()


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Deliberately does not touch the corpus or any upstream API: folding dependency health
    into liveness makes an orchestrator restart a process that is perfectly alive.
    """
    return {"status": "ok"}


@app.post("/v1/generate", response_model=GenerationResponse)
def generate(request: GenerationRequest) -> GenerationResponse:
    """Write the dispatch message, or refuse with `message: null`.

    A refusal is a 200 — it means we could have written something and declined to invent
    it. Only an unusable model or vector DB is a 503, which the backend treats exactly like
    a timeout and answers with its own `official_fallback`.
    """
    try:
        return generate_message(request, get_retriever(), get_generator())
    except GenerationFailedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/answer", response_model=AnswerResponse)
def answer(request: AnswerRequest) -> AnswerResponse:
    """Chatbot answer, or `answer: null` when nothing was retrieved to stand on."""
    try:
        return answer_question(request, get_retriever(), get_generator())
    except GenerationFailedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
