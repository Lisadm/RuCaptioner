import sys
import os
import sqlite3
import pytest

# Ensure we can import from backend
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from backend.config import get_settings

def test_caption_ru_column_exists():
    """Verify that the caption_ru column exists in the captions table."""
    settings = get_settings()
    db_path = settings.database.path
    
    # Resolve relative path if needed
    if not os.path.isabs(db_path):
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', db_path))
    
    print(f"Checking DB at: {db_path}")
    assert os.path.exists(db_path), f"Database file not found at {db_path}"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get table info
    cursor.execute("PRAGMA table_info(captions)")
    columns = [row[1] for row in cursor.fetchall()]
    
    conn.close()
    
    assert "caption_ru" in columns, f"Column 'caption_ru' is missing from 'captions' table. Found: {columns}"

if __name__ == "__main__":
    try:
        test_caption_ru_column_exists()
        print("TEST PASSED: 'caption_ru' column exists.")
        sys.exit(0)
    except AssertionError as e:
        print(f"TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"TEST ERROR: {e}")
        sys.exit(1)
