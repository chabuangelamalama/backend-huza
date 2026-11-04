from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.exceptions import AppError
from database import check_database, engine
from routers import admin, auth, business, notification, price_guide
from routers import businesses
from routers.enquiries import router as enquiries_router
from routers.listing import router as listing_router
from routers.payments import router as payments_router


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="HUZA API", version="0.1.0", lifespan=lifespan)

if settings.is_production:
    cors_options = {"allow_origins": settings.cors_origin_list}
else:
    cors_options = {"allow_origin_regex": r"https?://(localhost|127\.0\.0\.1)(:\d+)?"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(business.router)
app.include_router(listing_router)
app.include_router(enquiries_router)
app.include_router(enquiries_router, prefix="/api/v1", include_in_schema=False)
app.include_router(payments_router)
app.include_router(price_guide.router)
app.include_router(notification.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Readiness check: can the API reach the database?"""
    try:
        check_database()
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "error", "database": "down"}
        )
    return {"status": "ok", "database": "up"}


app.include_router(businesses.router)
