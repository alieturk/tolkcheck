from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging
from app.routers import auth, evaluations, sessions

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic. Run `alembic upgrade head` before starting.
    yield


app = FastAPI(
    title="Tolkcheck API",
    description="AI-powered interpreter quality evaluation for IND sessions",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(evaluations.router, prefix="/evaluations", tags=["evaluations"])


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
