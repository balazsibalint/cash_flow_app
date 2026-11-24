import os
import tempfile

# Az app importja ELŐTT: a tesztek soha ne a volume-ban lévő éles adatbázist használják,
# és ne induljon valódi LLM-hívás (a dev compose a .env-et is betölti).
_TMP = tempfile.mkdtemp(prefix="cashflow-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DATA_DIR"] = _TMP
os.environ["LLM_PROVIDER"] = "none"

import pytest  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db import Base, make_engine  # noqa: E402


@pytest.fixture
def db_session() -> Session:
    """Izolált, memóriabeli adatbázis tesztenként."""
    from app import models  # noqa: F401

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
