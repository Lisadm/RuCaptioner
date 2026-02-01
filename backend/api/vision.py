"""Vision model and auto-captioning API endpoints."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    VisionModelInfo, VisionGenerateRequest, VisionGenerateResponse,
    AutoCaptionJobCreate, CaptionJobResponse, CaptionJobProgress,
    TranslateRequest, TranslateResponse
)
from ..services.vision_service import VisionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])


@router.get("/models", response_model=List[VisionModelInfo])
async def list_vision_models(db: Session = Depends(get_db)):
    """List available vision models."""
    service = VisionService(db)
    return await service.list_models()


@router.post("/generate", response_model=VisionGenerateResponse)
async def generate_caption(
    request: VisionGenerateRequest,
    db: Session = Depends(get_db)
):
    """Generate a caption for a single image (for testing)."""
    service = VisionService(db)
    try:
        result = await service.generate_caption(
            file_id=request.file_id,
            style=request.style,
            max_length=request.max_length,
            vision_model=request.vision_model,
            vision_backend=request.vision_backend,
            template_id=request.template_id,
            seed=request.seed,
            custom_prompt=request.custom_prompt,
            trigger_phrase=request.trigger_phrase
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Error generating caption")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Caption generation failed: {str(e)}"
        )


@router.post("/translate", response_model=TranslateResponse)
async def translate_text(
    request: TranslateRequest,
    db: Session = Depends(get_db)
):
    """Translate text between Russian and English using the vision model."""
    service = VisionService(db)
    try:
        result = await service.translate_text(
            text=request.text,
            vision_model=request.vision_model,
            vision_backend=request.vision_backend,
            direction=request.direction or "ru_to_en"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Error translating text")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {str(e)}"
        )


@router.get("/jobs", response_model=List[CaptionJobResponse])
def list_caption_jobs(
    status_filter: str = None,
    db: Session = Depends(get_db)
):
    """List caption generation jobs."""
    service = VisionService(db)
    return service.list_jobs(status_filter=status_filter)


@router.get("/jobs/{job_id}", response_model=CaptionJobResponse)
def get_caption_job(job_id: str, db: Session = Depends(get_db)):
    """Get status of a caption generation job."""
    service = VisionService(db)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/pause", response_model=CaptionJobResponse)
def pause_caption_job(job_id: str, db: Session = Depends(get_db)):
    """Pause a running caption generation job."""
    service = VisionService(db)
    job = service.pause_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/resume", response_model=CaptionJobResponse)
async def resume_caption_job(job_id: str, db: Session = Depends(get_db)):
    """Resume a paused caption generation job."""
    service = VisionService(db)
    job = await service.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=CaptionJobResponse)
def cancel_caption_job(job_id: str, db: Session = Depends(get_db)):
    """Cancel a caption generation job."""
    service = VisionService(db)
    job = service.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(job_id: str, db: Session = Depends(get_db)):
    """Stream job progress updates via Server-Sent Events."""
    service = VisionService(db)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    
    async def event_generator():
        async for event in service.stream_job_progress(job_id):
            yield f"event: {event['type']}\ndata: {event['data']}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# Auto-caption endpoint (starts a job for a caption set)
@router.post("/caption-sets/{caption_set_id}/auto-generate", response_model=CaptionJobResponse)
async def start_auto_caption_job(
    caption_set_id: str,
    request: AutoCaptionJobCreate,
    db: Session = Depends(get_db)
):
    """Start auto-captioning for all files in a caption set."""
    service = VisionService(db)
    try:
        job = await service.start_auto_caption_job(
            caption_set_id=caption_set_id,
            vision_model=request.vision_model,
            vision_backend=request.vision_backend,
            template_id=request.template_id,
            seed=request.seed,
            seed_mode=request.seed_mode,
            overwrite_existing=request.overwrite_existing
        )
        return job
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
