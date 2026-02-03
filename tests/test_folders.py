import os
import pytest
from pathlib import Path
from PIL import Image
from backend.services.folder_service import FolderService
from backend.models import TrackedFolder, TrackedFile

def create_dummy_image(path: Path):
    """Helper to create a valid dummy image."""
    img = Image.new('RGB', (100, 100), color='red')
    img.save(path)

def test_add_folder(test_db, tmp_path):
    """Test adding a new folder to tracking."""
    service = FolderService(test_db)
    
    # Create a real directory
    folder_path = tmp_path / "test_set"
    folder_path.mkdir()
    
    # Add folder
    folder = service.create_folder(str(folder_path), name="Test Set")
    
    # Verify in DB
    assert folder.id is not None
    assert folder.name == "Test Set"
    assert folder.path == str(folder_path.resolve())
    
    # Verify persistence
    saved = test_db.query(TrackedFolder).first()
    assert saved.id == folder.id

def test_scan_folder(test_db, tmp_path):
    """Test scanning a folder finds images."""
    service = FolderService(test_db)
    
    # Setup: Create folder with images
    folder_path = tmp_path / "scan_target"
    folder_path.mkdir()
    
    img1 = folder_path / "image1.png"
    img2 = folder_path / "image2.jpg"
    txt1 = folder_path / "not_image.txt"
    
    create_dummy_image(img1)
    create_dummy_image(img2)
    txt1.write_text("Hello")
    
    # Add folder
    folder = service.create_folder(str(folder_path))
    
    # Service calls scan_folder inside create_folder, so files should be there
    files = test_db.query(TrackedFile).filter(TrackedFile.folder_id == folder.id).all()
    
    assert len(files) == 2
    filenames = {f.filename for f in files}
    assert "image1.png" in filenames
    assert "image2.jpg" in filenames
    assert "not_image.txt" not in filenames

def test_add_duplicate_folder(test_db, tmp_path):
    """Test correctly raises error for duplicate folder path."""
    service = FolderService(test_db)
    p = tmp_path / "dup"
    p.mkdir()
    
    service.create_folder(str(p))
    
    with pytest.raises(ValueError, match="Folder already tracked"):
        service.create_folder(str(p))

def test_invalid_path(test_db):
    """Test validation for non-existent paths."""
    service = FolderService(test_db)
    
    with pytest.raises(ValueError, match="Folder does not exist"):
        service.create_folder("/non/existent/path/12399")
