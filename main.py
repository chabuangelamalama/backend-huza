from fastapi import FastAPI

from routers.messaging import router as messaging_router

app = FastAPI(title="Huza", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


app.include_router(messaging_router)
