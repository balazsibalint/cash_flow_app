from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.services.extraction.llm import LlmClient
from app.services.extraction.pipeline import own_company
from app.services.ingest import IngestService
from app.services.llm_budget import DbLlmBudget
from app.services.mnb import MnbClient, RateService


def get_pdf_dir() -> Path:
    return Path(get_settings().data_dir) / "pdfs"


@lru_cache
def get_ingest() -> IngestService:
    """Folyamatonként egy példány: az LLM-szemafor és az újrapróbálási időzítő közös."""
    settings = get_settings()
    llm = None
    if (cfg := settings.llm) is not None:
        llm = LlmClient(cfg, timeout=settings.llm_timeout_seconds, max_concurrency=settings.llm_max_concurrency,
                        budget=DbLlmBudget(SessionLocal, settings.llm_max_calls_per_day))
    rates = RateService(MnbClient(settings.mnb_url, timeout=settings.mnb_timeout_seconds))
    return IngestService(SessionLocal, get_pdf_dir(), own_company(settings), llm=llm, rates=rates)
