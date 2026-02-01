
import sys
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add current dir to path to find modules if needed, but we'll try to import relatively or adjust
sys.path.append(os.getcwd())

from backend.models import TrackedFolder, TrackedFile, Base
from backend.database import get_database_path

def inspect_db():
    db_path = get_database_path()
    print(f"Database path: {db_path}")
    
    if not db_path.exists():
        print("Database not found!")
        return

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Find the folder
        # We look for a folder that has 'broken_katy' in the path or name
        folder = session.query(TrackedFolder).filter(TrackedFolder.path.like('%broken_katy%')).first()
        
        if not folder:
            print("Folder 'broken_katy' not found in DB.")
            # List all folders to be sure
            print("Available folders:")
            for f in session.query(TrackedFolder).all():
                print(f" - {f.name} ({f.path})")
            return

        print(f"Found Folder: {folder.name}")
        print(f"Path: {folder.path}")
        print(f"Last Scan: {folder.last_scan}")

        # Check specific file
        target_file = "E1arie1_00001_.png"
        f = session.query(TrackedFile).filter(TrackedFile.folder_id == folder.id, TrackedFile.filename == target_file).first()
        
        if f:
             print(f"Target File: {f.filename}")
             print(f"Imported Caption: {f.imported_caption!r}") # Use repr to see None or empty string
             print(f"Has Caption Property: {f.has_caption}")
        else:
             print(f"Target file {target_file} NOT FOUND in DB.")

        # Check files general stats
        files = session.query(TrackedFile).filter(TrackedFile.folder_id == folder.id).all()
        print(f"Total Files: {len(files)}")
        
        captioned_count = 0
        for f in files:
            if f.imported_caption:
                captioned_count += 1
                # print(f" - {f.filename}: HAS CAPTION ({len(f.imported_caption)} chars)")
            # else:
            #     print(f" - {f.filename}: NO CAPTION")
        
        print(f"Files with imported_caption: {captioned_count}")
        
        if captioned_count == 0 and len(files) > 0:
            print("0 files have imported captions. This confirms the scan missed them or hasn't run.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    inspect_db()
