from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db, get_ingest, get_pdf_dir
from app.config import get_settings
from app.models import Invoice
from app.schemas import InvoiceOut, UploadResult
from app.services.ingest import IngestService, InvalidUpload, check_upload, delete_all, delete_invoice

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.post("", response_model=UploadResult)
def upload_invoice(file: UploadFile, ingest: IngestService = Depends(get_ingest)) -> UploadResult:
    max_bytes = get_settings().max_upload_bytes
    data = file.file.read(max_bytes + 1)
    try:
        check_upload(data, max_bytes)
    except InvalidUpload as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ingest.ingest(file.filename or "", data)


@router.get("", response_model=list[InvoiceOut])
def list_invoices(db: Session = Depends(get_db)) -> list[Invoice]:
    return list(db.scalars(select(Invoice).options(selectinload(Invoice.partner))
                           .order_by(Invoice.created_at.desc(), Invoice.id.desc())))


@router.get("/{invoice_id}/pdf")
def get_pdf(invoice_id: int, db: Session = Depends(get_db), pdf_dir: Path = Depends(get_pdf_dir)) -> FileResponse:
    inv = db.get(Invoice, invoice_id)
    path = pdf_dir / f"{inv.file_sha256}.pdf" if inv else None
    if inv is None or not path.is_file():
        raise HTTPException(status_code=404, detail="A számla vagy a PDF nem található.")
    return FileResponse(path, media_type="application/pdf", filename=inv.filename, content_disposition_type="inline")


@router.delete("/{invoice_id}", status_code=204)
def remove_invoice(invoice_id: int, db: Session = Depends(get_db), pdf_dir: Path = Depends(get_pdf_dir)) -> Response:
    if not delete_invoice(db, invoice_id, pdf_dir):
        raise HTTPException(status_code=404, detail="A számla nem található.")
    return Response(status_code=204)


@router.delete("", status_code=204)
def remove_all_invoices(db: Session = Depends(get_db), pdf_dir: Path = Depends(get_pdf_dir)) -> Response:
    delete_all(db, pdf_dir)
    return Response(status_code=204)
