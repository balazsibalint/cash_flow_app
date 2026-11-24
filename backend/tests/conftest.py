import os
import tempfile


_TMP = tempfile.mkdtemp(prefix="cashflow-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DATA_DIR"] = _TMP
os.environ["LLM_PROVIDER"] = "none"

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, make_engine


@pytest.fixture
def db_session() -> Session:
    """Izolált, memóriabeli adatbázis tesztenként."""
    from app import models

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
