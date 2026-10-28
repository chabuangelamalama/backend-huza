from fastapi import FastAPI
from routers.payments import router as payments_router

app = FastAPI(title=" Huza", version="0.1.0")
app.include_router(payments_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Let deployment verification confirm that the API is responding."""
    return {"status": "ok"}
