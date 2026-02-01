"""File serving API endpoints (images and thumbnails)."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TrackedFile
from ..config import get_settings, PROJECT_ROOT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


class FileDetailResponse(BaseModel):
    """File detail response."""
    id: str
    folder_id: str
    filename: str
    relative_path: str
    absolute_path: str
    width: Optional[int]
    height: Optional[int]
    format: Optional[str]
    file_size: Optional[int]
    file_hash: Optional[str]
    has_caption: bool
    imported_caption: Optional[str]
    discovered_date: Optional[str]
    file_modified: Optional[str]
    
    class Config:
        from_attributes = True


class CaptionUpdate(BaseModel):
    """Caption update request."""
    text: str


@router.get("/{file_id}")
def get_file_details(file_id: str, db: Session = Depends(get_db)) -> FileDetailResponse:
    """Get detailed information about a file."""
    file = db.query(TrackedFile).filter(TrackedFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    return FileDetailResponse(
        id=file.id,
        folder_id=file.folder_id,
        filename=file.filename,
        relative_path=file.relative_path,
        absolute_path=file.absolute_path,
        width=file.width,
        height=file.height,
        format=file.format,
        file_size=file.file_size,
        file_hash=file.file_hash,
        has_caption=bool(file.imported_caption),
        imported_caption=file.imported_caption,
        discovered_date=file.discovered_date.isoformat() if file.discovered_date else None,
        file_modified=file.file_modified.isoformat() if file.file_modified else None
    )


@router.put("/{file_id}/caption")
def update_file_caption(
    file_id: str, 
    update: CaptionUpdate, 
    db: Session = Depends(get_db)
):
    """Update the imported caption for a file."""
    file = db.query(TrackedFile).filter(TrackedFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    file.imported_caption = update.text if update.text else None
    file.has_caption = bool(update.text)
    
    # Update the .txt file on disk
    try:
        txt_path = Path(file.absolute_path).with_suffix('.txt')
        if update.text:
            txt_path.write_text(update.text, encoding='utf-8')
        else:
            if txt_path.exists():
                txt_path.unlink()
    except Exception as e:
        # Log error but don't fail the request completely
        print(f"Failed to update caption file for {file.filename}: {e}")
        
    db.commit()
    
    return {"success": True, "message": "Caption updated"}


@router.get("/{file_id}/image")
def serve_image(file_id: str, db: Session = Depends(get_db)):
    """Serve the original image file."""
    file = db.query(TrackedFile).filter(TrackedFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    file_path = Path(file.absolute_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found on disk")
    
    # Determine media type
    ext = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file.filename
    )


@router.get("/{file_id}/thumbnail")
def serve_thumbnail(file_id: str, db: Session = Depends(get_db)):
    """Serve the thumbnail for a file."""
    file = db.query(TrackedFile).filter(TrackedFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    if not file.thumbnail_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not generated")
    
    settings = get_settings()
    thumbnail_dir = PROJECT_ROOT / settings.thumbnails.cache_path
    thumbnail_path = thumbnail_dir / file.thumbnail_path
    
    if not thumbnail_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail file not found")
    
    # Determine media type based on configured format
    format_media_types = {
        "webp": "image/webp",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }
    media_type = format_media_types.get(settings.thumbnails.format, "image/webp")
    
    return FileResponse(
        path=thumbnail_path,
        media_type=media_type
    )


@router.delete("/{file_id}")
def delete_file(file_id: str, db: Session = Depends(get_db)):
    """Delete a file and its associated resources."""
    from ..services.folder_service import FolderService
    
    service = FolderService(db)
    success = service.delete_file(file_id)
    
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    return {"success": True, "message": "File deleted"}
