from fastapi import FastAPI

from routers.enquiries import router as enquiries_router
from routers import notification, price_guide
from routers.listing import router as listing_router

app = FastAPI(title="HUZA API", version="0.1.0")

app.include_router(enquiries_router)
app.include_router(listing_router)
app.include_router(price_guide.router)
app.include_router(notification.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}
