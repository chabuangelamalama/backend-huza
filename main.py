from fastapi import FastAPI

app = FastAPI(title="Your Project Name", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Let deployment verification confirm that the API is responding."""
    return {"status": "ok"}
