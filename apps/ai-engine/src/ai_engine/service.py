"""FastAPI entrypoint for the independently deployable AI engine.

Keep routers thin: request validation -> engine call -> response mapping.
Retrieval/guardrail logic belongs in sibling modules of this package, which must
stay importable without FastAPI so the eval harness can call them directly.
"""

from fastapi import FastAPI

app = FastAPI(title="savers-ai-engine")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; replace with the /generate contract once it is fixed."""
    return {"status": "ok"}
