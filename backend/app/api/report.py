from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas import ReportOut
from app.services.report import build_report

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("", response_model=ReportOut)
def get_report(db: Session = Depends(get_db)) -> ReportOut:
    return build_report(db)
