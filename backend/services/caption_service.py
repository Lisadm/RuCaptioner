"""Caption management service."""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from ..models import CaptionSet, Caption, TrackedFile
from ..schemas import CaptionSetUpdate, CaptionCreate

logger = logging.getLogger(__name__)


class CaptionService:
    """Service for managing captions and caption sets."""
    
    def __init__(self, db: Session):
        self.db = db
    
    # Caption Set methods
    def get_caption_set(self, caption_set_id: str) -> Optional[CaptionSet]:
        """Get a caption set by ID."""
        return self.db.query(CaptionSet).filter(CaptionSet.id == caption_set_id).first()
    
    def update_caption_set(self, caption_set_id: str, update: CaptionSetUpdate) -> Optional[CaptionSet]:
        """Update a caption set."""
        caption_set = self.get_caption_set(caption_set_id)
        if not caption_set:
            return None
        
        if update.name is not None:
            # Check for duplicate name in same dataset
            existing = self.db.query(CaptionSet).filter(
                CaptionSet.dataset_id == caption_set.dataset_id,
                CaptionSet.name == update.name,
                CaptionSet.id != caption_set_id
            ).first()
            if existing:
                raise ValueError(f"Caption set '{update.name}' already exists in this dataset")
            caption_set.name = update.name
        
        if update.description is not None:
            caption_set.description = update.description
        if update.style is not None:
            caption_set.style = update.style
        if update.max_length is not None:
            caption_set.max_length = update.max_length
        if update.custom_prompt is not None:
            caption_set.custom_prompt = update.custom_prompt
        if update.trigger_phrase is not None:
            caption_set.trigger_phrase = update.trigger_phrase
        
        self.db.commit()
        self.db.refresh(caption_set)
        return caption_set
    
    def delete_caption_set(self, caption_set_id: str) -> bool:
        """Delete a caption set and all its captions."""
        caption_set = self.get_caption_set(caption_set_id)
        if not caption_set:
            return False
        
        self.db.delete(caption_set)
        self.db.commit()
        logger.info(f"Deleted caption set: {caption_set.name}")
        return True
    
    # Caption methods
    def get_caption(self, caption_id: str) -> Optional[Caption]:
        """Get a caption by ID."""
        return self.db.query(Caption).filter(Caption.id == caption_id).first()
    
    def get_caption_for_file(self, caption_set_id: str, file_id: str) -> Optional[Caption]:
        """Get caption for a specific file in a caption set."""
        return self.db.query(Caption).filter(
            Caption.caption_set_id == caption_set_id,
            Caption.file_id == file_id
        ).first()
    
    def list_captions(
        self, 
        caption_set_id: str, 
        page: int = 1, 
        page_size: int = 50
    ) -> List[Caption]:
        """List captions in a caption set."""
        return self.db.query(Caption).filter(
            Caption.caption_set_id == caption_set_id
        ).order_by(Caption.created_date).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
    
    def create_or_update_caption(
        self, 
        caption_set_id: str, 
        data: CaptionCreate
    ) -> Caption:
        """Create or update a caption for a file in a caption set."""
        import json
        
        # Verify file exists
        file = self.db.query(TrackedFile).filter(TrackedFile.id == data.file_id).first()
        if not file:
            raise ValueError(f"File not found: {data.file_id}")
        
        # Convert quality_flags list to JSON string if present
        quality_flags_json = None
        if data.quality_flags:
            quality_flags_json = json.dumps(data.quality_flags)
        
        # Check for existing caption
        caption = self.get_caption_for_file(caption_set_id, data.file_id)
        
        if caption:
            # Update existing
            caption.text = data.text
            caption.source = data.source
            if data.vision_model is not None:
                caption.vision_model = data.vision_model
            if data.quality_score is not None:
                caption.quality_score = data.quality_score
            if quality_flags_json is not None:
                caption.quality_flags = quality_flags_json
        else:
            # Create new
            caption = Caption(
                caption_set_id=caption_set_id,
                file_id=data.file_id,
                text=data.text,
                source=data.source,
                vision_model=data.vision_model,
                quality_score=data.quality_score,
                quality_flags=quality_flags_json
            )
            self.db.add(caption)
            
            # Update caption set count
            caption_set = self.get_caption_set(caption_set_id)
            if caption_set:
                caption_set.caption_count = self.db.query(Caption).filter(
                    Caption.caption_set_id == caption_set_id
                ).count() + 1
        
        self.db.commit()
        self.db.refresh(caption)
        
        # Also update quality score on DatasetFile if quality data is provided
        if data.quality_score is not None:
            from ..models import DatasetFile, CaptionSet
            caption_set = self.get_caption_set(caption_set_id)
            if caption_set:
                dataset_file = self.db.query(DatasetFile).filter(
                    DatasetFile.file_id == data.file_id,
                    DatasetFile.dataset_id == caption_set.dataset_id
                ).first()
                if dataset_file:
                    dataset_file.quality_score = data.quality_score
                    if quality_flags_json is not None:
                        dataset_file.quality_flags = quality_flags_json
                    self.db.commit()
        
        return caption
    
    def update_caption(self, caption_id: str, text: str) -> Optional[Caption]:
        """Update a caption's text."""
        caption = self.get_caption(caption_id)
        if not caption:
            return None
        
        caption.text = text
        caption.source = "manual"  # Mark as manually edited
        
        self.db.commit()
        self.db.refresh(caption)
        return caption
    
    def delete_caption(self, caption_id: str) -> bool:
        """Delete a caption."""
        caption = self.get_caption(caption_id)
        if not caption:
            return False
        
        caption_set_id = caption.caption_set_id
        self.db.delete(caption)
        
        # Update caption set count
        caption_set = self.get_caption_set(caption_set_id)
        if caption_set:
            caption_set.caption_count = self.db.query(Caption).filter(
                Caption.caption_set_id == caption_set_id
            ).count() - 1
        
        self.db.commit()
        return True
    
    def batch_update_captions(
        self, 
        caption_set_id: str, 
        captions: List[CaptionCreate]
    ) -> Dict[str, Any]:
        """Batch update multiple captions."""
        results = {
            "created": 0,
            "updated": 0,
            "errors": []
        }
        
        for caption_data in captions:
            try:
                existing = self.get_caption_for_file(caption_set_id, caption_data.file_id)
                self.create_or_update_caption(caption_set_id, caption_data)
                
                if existing:
                    results["updated"] += 1
                else:
                    results["created"] += 1
                    
            except Exception as e:
                results["errors"].append({
                    "file_id": caption_data.file_id,
                    "error": str(e)
                })
        
        return results
    
    def import_captions_from_files(self, caption_set_id: str, dataset_id: str) -> int:
        """Import captions from paired .txt files for all files in a dataset."""
        from ..models import DatasetFile
        
        imported = 0
        
        # Get all files in the dataset that have imported captions
        dataset_files = self.db.query(DatasetFile).join(
            TrackedFile, DatasetFile.file_id == TrackedFile.id
        ).filter(
            DatasetFile.dataset_id == dataset_id,
            TrackedFile.imported_caption.isnot(None)
        ).all()
        
        for df in dataset_files:
            file = df.file
            if not file.imported_caption:
                continue
            
            # Check if caption already exists
            existing = self.get_caption_for_file(caption_set_id, file.id)
            if existing:
                continue
            
            # Create caption from imported text
            caption = Caption(
                caption_set_id=caption_set_id,
                file_id=file.id,
                text=file.imported_caption,
                source="imported"
            )
            self.db.add(caption)
            imported += 1
        
        if imported > 0:
            # Update caption set count
            caption_set = self.get_caption_set(caption_set_id)
            if caption_set:
                caption_set.caption_count = self.db.query(Caption).filter(
                    Caption.caption_set_id == caption_set_id
                ).count()
            
            self.db.commit()
        
        logger.info(f"Imported {imported} captions from paired files")
        return imported
