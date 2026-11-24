import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import init_db
from app.schemas import HealthOut


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="CashFlow App API", lifespan=lifespan)


@app.get("/api/health", response_model=HealthOut)
def health_check() -> HealthOut:
    return HealthOut(status="ok", llm_enabled=get_settings().llm_enabled)


if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")