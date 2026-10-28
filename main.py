from fastapi import FastAPI

from routers import notification

app = FastAPI(title="HUZA API", version="0.1.0")
app.include_router(notification.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Let deployment verification confirm that the API is responding."""
    return {"status": "ok"}
