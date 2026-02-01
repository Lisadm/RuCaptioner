import os
import sys
import multiprocessing
import uvicorn
from backend.main import app

# Ensure backend package can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    # Needed for PyInstaller on Windows
    multiprocessing.freeze_support()
    
    # Get port from args or default
    port = 8765
    if len(sys.argv) > 1:
        # Simple arg parsing, Electron sends port as last arg usually if we configured it so,
        # but our main.js sends --port 8765. Uvicorn usually handles this via click,
        # but here we are calling uvicorn.run directly.
        # If we use main.js spawn logic: ['-m', 'uvicorn', ...] it expects python.
        # If we spawn exe, we might pass args differently.
        # Let's simple ignore args for now and use fixed port or parse if strictly needed.
        pass

    # Start Uvicorn
    # Note: reload=False is mandatory for frozen app
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info", reload=False)
