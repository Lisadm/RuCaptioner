import os
import sys
from alembic.config import Config
from alembic import command

# Ensure we are in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Add current dir to sys.path
sys.path.append(os.getcwd())

try:
    alembic_cfg = Config("alembic.ini")
    
    # Need to setup the env so alembic can find the app
    # This might require some setup if alembic.ini expects specific context
    # But revisions usually work if models are importable.
    
    command.revision(alembic_cfg, message="Add caption_ru", autogenerate=True)
    print("Migration generated successfully")
except Exception as e:
    print(f"Error generating migration: {e}")
