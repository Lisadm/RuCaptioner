"""Thumbnail generation service."""

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from ..config import get_settings, PROJECT_ROOT

logger = logging.getLogger(__name__)


class ThumbnailService:
    """Service for generating and managing image thumbnails."""
    
    def __init__(self):
        self.settings = get_settings()
        self.cache_dir = PROJECT_ROOT / self.settings.thumbnails.cache_path
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_thumbnail(
        self, 
        image_path: Path, 
        identifier: str
    ) -> str:
        """
        Generate a thumbnail for an image.
        
        Args:
            image_path: Path to the source image
            identifier: Unique identifier (hash or file ID) for the thumbnail filename
            
        Returns:
            Filename of the generated thumbnail (relative to cache dir)
        """
        max_size = self.settings.thumbnails.max_size
        quality = self.settings.thumbnails.quality
        thumb_format = self.settings.thumbnails.format.lower()
        
        # Determine output filename
        extension = {
            "webp": ".webp",
            "jpeg": ".jpg",
            "png": ".png"
        }.get(thumb_format, ".webp")
        
        thumbnail_filename = f"{identifier[:64]}{extension}"
        thumbnail_path = self.cache_dir / thumbnail_filename
        
        # Skip if thumbnail already exists
        if thumbnail_path.exists():
            return thumbnail_filename
        
        try:
            with Image.open(image_path) as img:
                # Convert to RGB if necessary (for JPEG/WebP)
                if img.mode in ('RGBA', 'LA', 'P') and thumb_format in ('jpeg', 'webp'):
                    # Create white background for transparency
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1])
                    img = background
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                
                # Calculate thumbnail size maintaining aspect ratio
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # Save thumbnail
                save_kwargs = {}
                if thumb_format == 'jpeg':
                    save_kwargs = {'quality': quality, 'optimize': True}
                elif thumb_format == 'webp':
                    save_kwargs = {'quality': quality, 'method': 4}
                elif thumb_format == 'png':
                    save_kwargs = {'optimize': True}
                
                img.save(thumbnail_path, format=thumb_format.upper(), **save_kwargs)
                
            logger.debug(f"Generated thumbnail: {thumbnail_filename}")
            return thumbnail_filename
            
        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {image_path}: {e}")
            raise
    
    def get_thumbnail_path(self, thumbnail_filename: str) -> Optional[Path]:
        """Get the full path to a thumbnail."""
        if not thumbnail_filename:
            return None
        path = self.cache_dir / thumbnail_filename
        return path if path.exists() else None
    
    def delete_thumbnail(self, thumbnail_filename: str) -> bool:
        """Delete a thumbnail file."""
        if not thumbnail_filename:
            return False
        path = self.cache_dir / thumbnail_filename
        if path.exists():
            path.unlink()
            return True
        return False
    
    def clear_cache(self) -> int:
        """Clear all cached thumbnails. Returns number of files deleted."""
        count = 0
        for f in self.cache_dir.glob("*"):
            if f.is_file() and f.name != ".gitkeep":
                f.unlink()
                count += 1
        logger.info(f"Cleared {count} thumbnails from cache")
        return count
    
    def get_cache_size(self) -> int:
        """Get total size of thumbnail cache in bytes."""
        total = 0
        for f in self.cache_dir.glob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total
