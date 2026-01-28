"""Export API endpoints."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ExportRequest, ExportResponse, ExportHistoryResponse
from ..services.export_service import ExportService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["export"])


@router.post("/datasets/{dataset_id}/export", response_model=ExportResponse)
async def start_export(
    dataset_id: str,
    request: ExportRequest,
    db: Session = Depends(get_db)
):
    """Start exporting a dataset."""
    service = ExportService(db)
    try:
        result = await service.start_export(dataset_id, request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Error starting export")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {str(e)}"
        )


@router.get("/jobs", response_model=List[ExportHistoryResponse])
def list_export_jobs(
    status_filter: str = None,
    db: Session = Depends(get_db)
):
    """List export jobs."""
    service = ExportService(db)
    return service.list_exports(status_filter=status_filter)


@router.get("/jobs/{export_id}", response_model=ExportHistoryResponse)
def get_export_job(export_id: str, db: Session = Depends(get_db)):
    """Get status of an export job."""
    service = ExportService(db)
    export = service.get_export(export_id)
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    return export


@router.get("/jobs/{export_id}/download")
def download_export(export_id: str, db: Session = Depends(get_db)):
    """Download a ZIP export."""
    service = ExportService(db)
    export = service.get_export(export_id)
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    
    if export.export_type != "zip":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Only ZIP exports can be downloaded"
        )
    
    if export.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Export is not complete"
        )
    
    zip_path = service.get_export_zip_path(export_id)
    if not zip_path or not zip_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export file not found")
    
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=zip_path.name
    )


@router.get("/history", response_model=List[ExportHistoryResponse])
def get_export_history(
    dataset_id: str = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Get export history, optionally filtered by dataset."""
    service = ExportService(db)
    return service.get_history(dataset_id=dataset_id, limit=limit)
