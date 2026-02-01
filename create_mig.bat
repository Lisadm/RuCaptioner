@echo off
call venv\Scripts\activate.bat
echo Generating migration...
alembic revision --autogenerate -m "Add caption_ru"
if errorlevel 1 (
    echo FAILED to generate migration
    exit /b 1
)
echo SUCCESS
