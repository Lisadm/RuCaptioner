"""System API endpoints."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db, get_database_path
from ..config import get_settings, PROJECT_ROOT
from ..schemas import SystemStatsResponse, HealthResponse
from ..models import TrackedFolder, TrackedFile, Dataset, CaptionSet, Caption
from .. import __version__

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """Check system health."""
    from sqlalchemy import text
    settings = get_settings()
    
    # Check database
    db_connected = False
    try:
        db.execute(text("SELECT 1"))
        db_connected = True
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        pass
    
    # Check Ollama availability
    ollama_available = False
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.vision.ollama_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                ollama_available = resp.status == 200
    except Exception:
        pass
    
    # Check LM Studio availability
    lmstudio_available = False
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.vision.lmstudio_url}/v1/models",
                timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                lmstudio_available = resp.status == 200
    except Exception:
        pass
    
    return HealthResponse(
        status="healthy" if db_connected else "unhealthy",
        version=__version__,
        database_connected=db_connected,
        ollama_available=ollama_available,
        lmstudio_available=lmstudio_available
    )


@router.get("/stats", response_model=SystemStatsResponse)
def get_system_stats(db: Session = Depends(get_db)):
    """Get system-wide statistics."""
    settings = get_settings()
    
    # Count entities
    total_folders = db.query(TrackedFolder).count()
    total_files = db.query(TrackedFile).count()
    total_datasets = db.query(Dataset).count()
    total_caption_sets = db.query(CaptionSet).count()
    total_captions = db.query(Caption).count()
    
    # Get database size
    db_path = get_database_path()
    database_size = db_path.stat().st_size if db_path.exists() else 0
    
    # Get thumbnail cache size
    thumbnail_dir = PROJECT_ROOT / settings.thumbnails.cache_path
    thumbnail_size = 0
    if thumbnail_dir.exists():
        for f in thumbnail_dir.glob("*"):
            if f.is_file():
                thumbnail_size += f.stat().st_size
    
    return SystemStatsResponse(
        total_folders=total_folders,
        total_files=total_files,
        total_datasets=total_datasets,
        total_caption_sets=total_caption_sets,
        total_captions=total_captions,
        database_size_bytes=database_size,
        thumbnail_cache_size_bytes=thumbnail_size
    )


@router.get("/config")
def get_config():
    """Get current system configuration for settings modal."""
    settings = get_settings()
    
    return {
        "vision": {
            "backend": settings.vision.backend,
            "ollama_url": settings.vision.ollama_url,
            "lmstudio_url": settings.vision.lmstudio_url,
            "default_model": settings.vision.default_model,
            "timeout_seconds": settings.vision.timeout_seconds,
            "max_retries": settings.vision.max_retries,
            "max_tokens": settings.vision.max_tokens,
        },
        "thumbnails": {
            "max_size": settings.thumbnails.max_size,
            "quality": settings.thumbnails.quality,
            "format": settings.thumbnails.format,
        },
        "export": {
            "default_format": settings.export.default_format,
            "default_quality": settings.export.default_quality,
            "default_padding": settings.export.default_padding,
        },
        "image_processing": {
            "supported_formats": settings.image_processing.supported_formats,
            "max_file_size_mb": settings.image_processing.max_file_size_mb,
        },
        "server": {
            "debug": settings.server.debug,
        }
    }


@router.post("/config")
async def save_config(config: dict):
    """Save system configuration to settings.yaml."""
    import yaml
    from ..config import PROJECT_ROOT, get_config_loader
    
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    
    # Load existing config to preserve comments structure
    existing = {}
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            existing = yaml.safe_load(f) or {}
    
    # Update only the sections we manage
    if "vision" in config:
        existing["vision"] = {
            "backend": config["vision"].get("backend", "ollama"),
            "ollama_url": config["vision"].get("ollama_url", "http://localhost:11434"),
            "lmstudio_url": config["vision"].get("lmstudio_url", "http://localhost:1234"),
            "default_model": config["vision"].get("default_model", "qwen3-vl:4b"),
            "timeout_seconds": int(config["vision"].get("timeout_seconds", 120)),
            "max_retries": int(config["vision"].get("max_retries", 2)),
            "max_tokens": int(config["vision"].get("max_tokens", 4096)),
        }
    
    if "thumbnails" in config:
        existing["thumbnails"] = {
            "max_size": int(config["thumbnails"].get("max_size", 256)),
            "quality": int(config["thumbnails"].get("quality", 85)),
            "format": config["thumbnails"].get("format", "webp"),
            "cache_path": existing.get("thumbnails", {}).get("cache_path", "data/thumbnails"),
        }
    
    if "export" in config:
        existing["export"] = {
            "default_format": config["export"].get("default_format", "jpeg"),
            "default_quality": int(config["export"].get("default_quality", 95)),
            "default_padding": int(config["export"].get("default_padding", 6)),
            "staging_path": existing.get("export", {}).get("staging_path", "data/exports"),
        }
    
    if "server" in config:
        existing["server"] = {
            **existing.get("server", {}),
            "debug": config["server"].get("debug", False),
        }
    
    # Write the updated config
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    # Reload settings in memory
    get_config_loader().reload()
    
    logger.info(f"Configuration saved to {config_path}")
    
    return {"status": "ok", "message": "Configuration saved. Some changes may require a restart."}


@router.post("/test-connection/{backend}")
async def test_backend_connection(backend: str):
    """Test connection to a vision backend."""
    settings = get_settings()
    
    try:
        import aiohttp
        
        if backend == "ollama":
            url = f"{settings.vision.ollama_url}/api/tags"
        elif backend == "lmstudio":
            url = f"{settings.vision.lmstudio_url}/v1/models"
        else:
            return {"status": "error", "message": f"Unknown backend: {backend}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if backend == "ollama":
                        model_count = len(data.get("models", []))
                        return {"status": "ok", "message": f"Connected! {model_count} models available."}
                    else:
                        model_count = len(data.get("data", []))
                        return {"status": "ok", "message": f"Connected! {model_count} models loaded."}
                else:
                    return {"status": "error", "message": f"Server returned status {resp.status}"}
    
    except asyncio.TimeoutError:
        return {"status": "error", "message": "Connection timed out"}
    except aiohttp.ClientConnectorError:
        return {"status": "error", "message": f"Cannot connect to {backend}. Is it running?"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
