from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.config import get_settings
from app.db import engine
from app.main import app


def test_startup_creates_tables_and_data_dir():
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "llm_enabled": False}

    tables = set(inspect(engine).get_table_names())
    assert {"invoices", "partners", "exchange_rates", "mnb_fetches", "llm_calls"} <= tables
    assert Path(get_settings().data_dir, "pdfs").is_dir()
