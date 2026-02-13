"""Vision model integration service for auto-captioning."""

import asyncio
import base64
import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

# import aiohttp
# from PIL import Image
from sqlalchemy.orm import Session

from ..config import get_settings, PROJECT_ROOT
from ..models import TrackedFile, CaptionSet, Caption, CaptionJob, VisionModel
from ..schemas import VisionModelInfo, VisionGenerateResponse, CaptionJobResponse

logger = logging.getLogger(__name__)


# Curated vision models with known good performance
CURATED_MODELS = [
    {
        "model_id": "qwen2.5-vl-7b",
        "name": "Qwen2.5-VL 7B",
        "lmstudio_name": "qwen/qwen2.5-vl-7b-instruct",
        "vram_gb": 8.0,
        "description": "Excellent quality, good speed. Recommended for most users."
    },
    {
        "model_id": "qwen2.5-vl-3b",
        "name": "Qwen2.5-VL 3B",
        "lmstudio_name": "qwen/qwen2.5-vl-3b-instruct",
        "vram_gb": 4.0,
        "description": "Fast and lightweight. Good for quick iterations."
    },
    {
        "model_id": "llava-1.6-34b",
        "name": "LLaVA 1.6 34B",
        "lmstudio_name": "liuhaotian/llava-v1.6-34b",
        "vram_gb": 24.0,
        "description": "Highest quality, requires significant VRAM."
    },
    {
        "model_id": "llava-1.6-13b",
        "name": "LLaVA 1.6 13B",
        "lmstudio_name": "liuhaotian/llava-v1.6-13b",
        "vram_gb": 12.0,
        "description": "Good balance of quality and speed."
    },
    {
        "model_id": "llava-1.6-7b",
        "name": "LLaVA 1.6 7B",
        "lmstudio_name": "liuhaotian/llava-v1.6-7b",
        "vram_gb": 6.0,
        "description": "Efficient option for lower VRAM systems."
    },
]

# Curated prompt templates
PROMPT_TEMPLATES = {
    "detailed_p": "Напиши ОДИН подробный абзац (6–10 предложений). Описывай только то, что видно: объект(ы) и действия; детали людей, если они есть (примерный возраст, гендерное выражение — если очевидно, волосы, мимика, поза, одежда, аксессуары); окружение (тип локации, элементы фона, признаки времени); освещение (источник, направление, мягкость/жёсткость, цветовая температура, тени); точку съёмки камеры (на уровне глаз / ниже / выше, дистанция) и композицию (кадрирование, акценты). Без вступлений, без рассуждений, без <think>.",
    "ultra": "Напиши ОДИН ультрадетальный абзац (10–16 предложений, ~180–320 слов). Опираться только на видимые детали. Включи: микродетали объекта (материалы, текстуры, узоры, износ, отражения); детали людей, если есть (волосы, тон кожи, макияж, украшения, типы тканей, посадка одежды); глубину окружения (передний/средний/задний план, вывески/предметы, материалы поверхностей); анализ освещения (ключевой/заполняющий/контровой свет, направление, мягкость, блики, форма теней); перспективу камеры (угол, “ощущение” объектива, глубина резкости) и композицию (ведущие линии, негативное пространство, симметрия/асимметрия, визуальная иерархия). Без вступлений, без рассуждений, без <think>.",
    "cinematic": "Напиши ОДИН кинематографичный абзац (8–12 предложений). Опиши сцену как стоп-кадр из фильма: объект(ы) и действие; окружение и атмосферу; световую схему (практические источники света vs рассеянный, направление, контраст); язык камеры (тип плана, угол, ощущение объектива, глубина резкости, подразумеваемое движение); композицию и настроение. Ярко, но фактически (без выдуманного сюжета). Без вступлений, без рассуждений, без <think>.",
    "tags": "Act as an image-to-tag interrogation system. Your goal is to describe the image using a comprehensive list of tags in Danbooru style (booru-tags).\n\nSTRICT RULES:\nOutput ONLY tags separated by commas.\nNO introductory text, NO explanations, NO conversational filler.\nUse English only.\nUse underscores for multi-word tags (e.g., depth_of_field, long_hair).\nOrder: general tags, character/subject details, clothing/accessories, pose, background, lighting/effects, artistic style, technical parameters.\nBe extremely detailed: include specific colors, textures, camera angles, and atmosphere.\nTask: Analyze this image and provide the tag list.",
}


class VisionService:
    """Service for vision model integration and auto-captioning."""
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self._active_jobs: Dict[str, bool] = {}  # job_id -> is_paused
        self._resize_cache: Dict[str, bytes] = {}  # file_id -> resized image bytes (cleared per job)
    
    async def list_models(self) -> List[VisionModelInfo]:
        """List available vision models from the configured backend."""
        models = []
        backend = self.settings.vision.backend
        
        try:
            if backend == "lmstudio":
                models = await self._get_lmstudio_models()
        except Exception as e:
            logger.warning(f"Failed to fetch models from {backend}: {e}")
        
        # If no models found from API, fall back to curated list with availability check
        if not models:
            logger.debug("No models from API, falling back to curated list")
            for model in CURATED_MODELS:
                backend_name = model["lmstudio_name"]
                is_available = await self._check_model_available(backend, backend_name)
                
                models.append(VisionModelInfo(
                    model_id=model["model_id"],
                    name=model["name"],
                    backend=backend,
                    backend_model_name=backend_name,
                    is_available=is_available,
                    vram_gb=model["vram_gb"],
                    description=model["description"]
                ))
        
        return models
    
    async def _get_lmstudio_models(self) -> List[VisionModelInfo]:
        """Fetch available models from LM Studio API."""
        import aiohttp
        models = []
        url = f"{self.settings.vision.lmstudio_url}/v1/models"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for model_data in data.get("data", []):
                            model_id = model_data.get("id", "")
                            # Extract a friendly name from the model ID
                            name = model_id.split("/")[-1] if "/" in model_id else model_id
                            
                            models.append(VisionModelInfo(
                                model_id=model_id,
                                name=name,
                                backend="lmstudio",
                                backend_model_name=model_id,
                                is_available=True,
                                vram_gb=None,
                                description=f"Loaded in LM Studio"
                            ))
                        logger.info(f"Found {len(models)} models in LM Studio")
        except Exception as e:
            logger.debug(f"Could not fetch LM Studio models: {e}")
        
        return models
    

    
    async def generate_caption(
        self,
        file_id: str,
        style: str = "natural",
        max_length: Optional[int] = None,
        vision_model: Optional[str] = None,
        vision_backend: Optional[str] = None,
        template_id: Optional[str] = None,
        seed: Optional[int] = None,
        custom_prompt: Optional[str] = None,
        trigger_phrase: Optional[str] = None
    ) -> VisionGenerateResponse:
        """Generate a caption for a single image."""
        # Get file
        file = self.db.query(TrackedFile).filter(TrackedFile.id == file_id).first()
        if not file:
            raise ValueError(f"File not found: {file_id}")
        
        file_path = Path(file.absolute_path)
        if not file_path.exists():
            raise ValueError(f"Image file not found on disk: {file_path}")
        
        # Determine backend and model
        backend = vision_backend or self.settings.vision.backend
        model = vision_model or self.settings.vision.default_model
        
        # Build prompt
        prompt = self._build_prompt(style, max_length, custom_prompt, trigger_phrase, template_id)
        logger.debug(f"Vision prompt for style '{style}': {prompt[:200]}...")
        
        # Generate caption
        start_time = time.time()
        result = await self._call_vision_model(backend, model, file_path, prompt, file_id, seed=seed)
        processing_time = int((time.time() - start_time) * 1000)
        
        logger.debug(f"Vision model raw result: {result}")
        
        # Ensure caption starts with trigger phrase if provided
        caption = result["caption"]
        if not caption or not caption.strip():
            logger.warning(f"Vision model returned empty caption for file {file_id}")
            caption = ""
        
        if trigger_phrase and caption and not caption.lower().startswith(trigger_phrase.lower()):
            # Prepend trigger phrase if model didn't include it
            caption = f"{trigger_phrase}, {caption}" if not caption.startswith(',') else f"{trigger_phrase}{caption}"
        
        return VisionGenerateResponse(
            caption=caption,
            quality_score=result.get("quality_score"),
            quality_flags=result.get("quality_flags"),
            processing_time_ms=processing_time,
            vision_model=model,
            backend=backend,
            caption_ru=result.get("caption_ru")
        )
    
    async def translate_text(
        self,
        text: str,
        vision_model: Optional[str] = None,
        vision_backend: Optional[str] = None,
        direction: str = "ru_to_en"  # "ru_to_en" or "en_to_ru"
    ) -> Dict[str, Any]:
        """Translate text between Russian and English using LLM."""
        import time
        start_time = time.time()
        
        # Get configured backend and model
        backend = vision_backend or self.settings.vision.backend
        model = vision_model or self.settings.vision.default_model
        
        # Build translation prompt based on direction
        if direction == "en_to_ru":
            prompt = f"""You are a professional translator. Translate the following English text to Russian. 
Provide ONLY the translation, no explanations, no quotes, no extra text.
Maintain the style and tone of the original description.

English text:
{text}

Russian translation:"""
        else:  # ru_to_en (default)
            prompt = f"""You are a professional translator. Translate the following Russian text to English. 
Provide ONLY the translation, no explanations, no quotes, no extra text.
Maintain the style and tone of the original description.

Russian text:
{text}

English translation:"""
        
        # Call the model (text-only, no image)
        if backend == "ollama":
            response = await self._call_ollama_text(model, prompt)
        else:  # lmstudio
            response = await self._call_lmstudio_text(model, prompt)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Clean up response
        translated = response.strip()
        # Remove quotes if the model wrapped the response
        if translated.startswith('"') and translated.endswith('"'):
            translated = translated[1:-1]
        if translated.startswith("'") and translated.endswith("'"):
            translated = translated[1:-1]
        
        return {
            "translated_text": translated,
            "processing_time_ms": processing_time,
            "vision_model": model,
            "backend": backend,
            "direction": direction
        }

    
    def list_jobs(self, status_filter: Optional[str] = None) -> List[CaptionJob]:
        """List caption generation jobs."""
        query = self.db.query(CaptionJob)
        if status_filter:
            query = query.filter(CaptionJob.status == status_filter)
        return query.order_by(CaptionJob.created_date.desc()).all()
    
    def get_job(self, job_id: str) -> Optional[CaptionJob]:
        """Get a job by ID."""
        return self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
    
    def pause_job(self, job_id: str) -> Optional[CaptionJob]:
        """Pause a running job."""
        job = self.get_job(job_id)
        if not job or job.status != "running":
            return job
        
        job.status = "paused"
        self._active_jobs[job_id] = True  # Signal pause
        self.db.commit()
        self.db.refresh(job)
        return job
    
    async def resume_job(self, job_id: str) -> Optional[CaptionJob]:
        """Resume a paused job."""
        job = self.get_job(job_id)
        if not job or job.status != "paused":
            return job
        
        job.status = "running"
        self._active_jobs[job_id] = False  # Signal resume
        self.db.commit()
        self.db.refresh(job)
        
        # Restart the background task to continue processing
        import asyncio
        asyncio.create_task(self._run_caption_job(job_id))
        
        return job
    
    def cancel_job(self, job_id: str) -> Optional[CaptionJob]:
        """Cancel a job."""
        job = self.get_job(job_id)
        if not job or job.status in ("completed", "cancelled"):
            return job
        
        job.status = "cancelled"
        if job_id in self._active_jobs:
            del self._active_jobs[job_id]
        self.db.commit()
        self.db.refresh(job)
        return job
    
    def clear_all_jobs(self) -> int:
        """Delete all jobs from the database."""
        # Cancel any running jobs first
        for job_id in list(self._active_jobs.keys()):
            del self._active_jobs[job_id]
        
        # Delete all jobs
        count = self.db.query(CaptionJob).delete()
        self.db.commit()
        return count
    
    async def start_auto_caption_job(
        self,
        caption_set_id: str,
        vision_model: Optional[str] = None,
        vision_backend: Optional[str] = None,
        template_id: Optional[str] = None,
        seed: Optional[int] = None,
        seed_mode: Optional[str] = "fixed",
        overwrite_existing: bool = False
    ) -> CaptionJob:
        """Start auto-captioning for a caption set."""
        # Verify caption set exists
        caption_set = self.db.query(CaptionSet).filter(
            CaptionSet.id == caption_set_id
        ).first()
        if not caption_set:
            raise ValueError(f"Caption set not found: {caption_set_id}")
        
        backend = vision_backend or self.settings.vision.backend
        model = vision_model or self.settings.vision.default_model
        
        # Count files to process
        from ..models import DatasetFile
        query = self.db.query(DatasetFile).filter(
            DatasetFile.dataset_id == caption_set.dataset_id,
            DatasetFile.excluded == False
        )
        
        if not overwrite_existing:
            # Exclude files that already have captions
            existing_captions = self.db.query(Caption.file_id).filter(
                Caption.caption_set_id == caption_set_id
            )
            query = query.filter(~DatasetFile.file_id.in_(existing_captions))
        
        total_files = query.count()
        
        if total_files == 0:
            raise ValueError("No files to caption (all files may already have captions)")
        
        # Create job
        job = CaptionJob(
            caption_set_id=caption_set_id,
            vision_model=model,
            vision_backend=backend,
            template_id=template_id or caption_set.template_id,
            seed=seed,
            seed_mode=seed_mode,
            overwrite_existing=overwrite_existing,
            status="pending",
            total_files=total_files
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        
        logger.info(f"Created caption job {job.id} for {total_files} files")
        
        # Start job in background (simplified - real implementation would use task queue)
        asyncio.create_task(self._run_caption_job(job.id))
        
        return job
    
    async def stream_job_progress(self, job_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream job progress updates via SSE."""
        while True:
            job = self.get_job(job_id)
            if not job:
                yield {
                    "type": "error",
                    "data": json.dumps({"error": "Job not found"})
                }
                break
            
            percent = (job.completed_files / job.total_files * 100) if job.total_files > 0 else 0
            
            yield {
                "type": "progress",
                "data": json.dumps({
                    "job_id": job_id,
                    "status": job.status,
                    "completed_files": job.completed_files,
                    "total_files": job.total_files,
                    "failed_files": job.failed_files,
                    "percent_complete": round(percent, 1),
                    "current_file_id": job.current_file_id
                })
            }
            
            if job.status in ("completed", "failed", "cancelled"):
                break
            
            await asyncio.sleep(1)  # Update every second
    
    async def _run_caption_job(self, job_id: str):
        """Run a caption generation job."""
        job = self.get_job(job_id)
        if not job:
            return
        
        # Clear resize cache at start of job
        self._resize_cache.clear()
        logger.info(f"Starting caption job {job_id}, resize cache cleared")
        
        # Only set started_date on first run, not on resume
        if not job.started_date:
            job.started_date = datetime.utcnow()
        job.status = "running"
        self.db.commit()
        
        self._active_jobs[job_id] = False  # Not paused
        
        # Cache caption set ID for later use
        caption_set_id = job.caption_set_id
        
        try:
            caption_set = self.db.query(CaptionSet).filter(
                CaptionSet.id == caption_set_id
            ).first()
            
            if not caption_set:
                raise ValueError("Caption set not found")
            
            # Cache caption set properties to avoid detached instance issues
            cs_style = caption_set.style
            cs_template_id = caption_set.template_id
            cs_max_length = caption_set.max_length
            cs_custom_prompt = caption_set.custom_prompt
            cs_trigger_phrase = caption_set.trigger_phrase
            cs_dataset_id = caption_set.dataset_id
            
            # Determine job template (job template overrides set template)
            job_template_id = job.template_id or cs_template_id
            
            logger.info(f"Caption job {job_id}: style={cs_style}, template={job_template_id}, custom_prompt={'yes (' + str(len(cs_custom_prompt)) + ' chars)' if cs_custom_prompt else 'no'}, trigger={cs_trigger_phrase}")
            
            # Get file IDs to process (just the IDs, not full objects)
            from ..models import DatasetFile
            
            # Update job's completed count (handles resume)
            job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
            if job:
                # When overwriting, completed_files tracks files processed, not captions created
                # When not overwriting, it tracks captions created (already existing ones)
                if not job.overwrite_existing:
                    existing_caption_count = self.db.query(Caption).filter(
                        Caption.caption_set_id == caption_set_id
                    ).count()
                    job.completed_files = existing_caption_count
                # If overwriting, keep completed_files as-is (tracks actual processing)
                self.db.commit()
            
            # Build query for files to process
            query = self.db.query(DatasetFile.file_id).filter(
                DatasetFile.dataset_id == cs_dataset_id,
                DatasetFile.excluded == False
            ).order_by(DatasetFile.order_index, DatasetFile.file_id)
            
            # Only skip existing captions if overwrite_existing is False
            if not job.overwrite_existing:
                existing_caption_file_ids = self.db.query(Caption.file_id).filter(
                    Caption.caption_set_id == caption_set_id
                ).subquery()
                query = query.filter(~DatasetFile.file_id.in_(existing_caption_file_ids))
            
            file_ids_to_process = query.all()
            
            # Extract just the IDs as a list
            file_ids = [f[0] for f in file_ids_to_process]

            # If overwriting, we need to skip files that were already processed in this job run
            # (completed_files + failed_files)
            if job.overwrite_existing and (job.completed_files > 0 or job.failed_files > 0):
                processed_count = job.completed_files + job.failed_files
                if processed_count < len(file_ids):
                    logger.info(f"Resuming job {job_id}: skipping first {processed_count} already processed files")
                    file_ids = file_ids[processed_count:]
                else:
                    logger.info(f"Resuming job {job_id}: all files appear to be processed")
                    file_ids = []
            
            logger.info(f"Caption job {job_id}: {len(file_ids)} files remaining to process")
            
            for file_id in file_ids:
                # Re-fetch job to get fresh state and check for pause/cancel
                job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
                if not job or job.status == "cancelled":
                    break
                    
                if job.status == "paused":
                    # Wait while paused
                    while True:
                        await asyncio.sleep(1)
                        job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
                        if not job or job.status == "cancelled":
                            break
                        if job.status != "paused":
                            break
                    if not job or job.status == "cancelled":
                        break
                
                # Update current file
                job.current_file_id = file_id
                self.db.commit()
                
                try:
                    # Generate caption
                    result = await self.generate_caption(
                        file_id=file_id,
                        style=cs_style,
                        max_length=cs_max_length,
                        vision_model=job.vision_model,
                        vision_backend=job.vision_backend,
                        template_id=job_template_id,
                        seed=job.seed,
                        custom_prompt=cs_custom_prompt,
                        trigger_phrase=cs_trigger_phrase
                    )
                    
                    # Re-fetch job after async operation
                    job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
                    if not job:
                        break
                    
                    # Save or update caption
                    existing_caption = self.db.query(Caption).filter(
                        Caption.caption_set_id == job.caption_set_id,
                        Caption.file_id == file_id
                    ).first()
                    
                    if existing_caption:
                        # Update existing caption
                        existing_caption.text = result.caption
                        existing_caption.source = "generated"
                        existing_caption.vision_model = job.vision_model
                        existing_caption.quality_score = result.quality_score
                        existing_caption.quality_flags = json.dumps(result.quality_flags) if result.quality_flags else None
                        if result.caption_ru:
                            existing_caption.caption_ru = result.caption_ru
                    else:
                        # Create new caption
                        caption = Caption(
                            caption_set_id=job.caption_set_id,
                            file_id=file_id,
                            text=result.caption,
                            source="generated",
                            vision_model=job.vision_model,
                            quality_score=result.quality_score,
                            quality_flags=json.dumps(result.quality_flags) if result.quality_flags else None,
                            caption_ru=result.caption_ru
                        )
                        self.db.add(caption)
                    
                    # Update quality score on dataset file
                    if result.quality_score:
                        dataset_file = self.db.query(DatasetFile).filter(
                            DatasetFile.file_id == file_id,
                            DatasetFile.dataset_id == cs_dataset_id
                        ).first()
                        if dataset_file:
                            dataset_file.quality_score = result.quality_score
                            dataset_file.quality_flags = json.dumps(result.quality_flags) if result.quality_flags else None
                    
                    # Increment completed counter (tracks files processed, regardless of new/update)
                    job.completed_files += 1
                    logger.debug(f"Caption job {job_id}: processed file, completed {job.completed_files}/{job.total_files} files")
                    
                except Exception as e:
                    logger.error(f"Failed to caption file {file_id}: {e}")
                    job.failed_files += 1
                    job.last_error = str(e)
                
                self.db.commit()
            
            # Job completed - re-fetch to ensure we have fresh state
            job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
            if job and job.status not in ("cancelled",):
                job.status = "completed"
                job.completed_date = datetime.utcnow()
                logger.info(f"Caption job {job_id} completed: {job.completed_files} files, {job.failed_files} failed")
            
            # Update caption set count
            caption_set_updated = self.db.query(CaptionSet).filter(
                CaptionSet.id == caption_set_id
            ).first()
            if caption_set_updated:
                caption_set_updated.caption_count = self.db.query(Caption).filter(
                    Caption.caption_set_id == caption_set_id
                ).count()
            
        except Exception as e:
            logger.exception(f"Caption job {job_id} failed")
            job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.last_error = str(e)
        
        finally:
            if job_id in self._active_jobs:
                del self._active_jobs[job_id]
            # Clear resize cache when job finishes
            cache_size = len(self._resize_cache)
            self._resize_cache.clear()
            logger.info(f"Caption job {job_id} finished, cleared {cache_size} cached images from memory")
            self.db.commit()
    
    async def _check_model_available(self, backend: str, model_name: str) -> bool:
        """Check if a model is available in the backend."""
        try:
            if backend == "ollama":
                import aiohttp
                url = f"{self.settings.vision.ollama_url}/api/tags"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            models = [m["name"] for m in data.get("models", [])]
                            return model_name in models
            elif backend == "lmstudio":
                import aiohttp
                url = f"{self.settings.vision.lmstudio_url}/v1/models"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            models = [m["id"] for m in data.get("data", [])]
                            return any(model_name in m for m in models)
        except Exception as e:
            logger.debug(f"Could not check model availability: {e}")
        return False
    
    def _resize_image_for_vision(self, image_path: Path, file_id: str) -> bytes:
        """
        Resize image for vision model inference.
        Returns JPEG bytes of the resized image.
        Uses in-memory cache during caption jobs.
        """
        # Check cache first
        if file_id in self._resize_cache:
            logger.debug(f"Using cached resized image for file {file_id}")
            return self._resize_cache[file_id]
        
        config = self.settings.vision.preprocessing
        max_size = config.max_resolution
        quality = config.resize_quality
        output_format = config.format.upper()
        
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                # Get original dimensions
                orig_width, orig_height = img.size
                
                # Check if resize is needed
                if max(orig_width, orig_height) <= max_size:
                    # Image is already small enough, just convert format if needed
                    logger.debug(f"Image {file_id} is {orig_width}x{orig_height}, no resize needed")
                else:
                    # Calculate new dimensions maintaining aspect ratio
                    if config.maintain_aspect_ratio:
                        if orig_width > orig_height:
                            new_width = max_size
                            new_height = int(orig_height * (max_size / orig_width))
                        else:
                            new_height = max_size
                            new_width = int(orig_width * (max_size / orig_height))
                    else:
                        new_width = new_height = max_size
                    
                    logger.debug(f"Resizing image {file_id} from {orig_width}x{orig_height} to {new_width}x{new_height}")
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Convert to RGB if necessary (for JPEG)
                if output_format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background for transparency
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1])
                    img = background
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                
                # Save to bytes buffer
                buffer = io.BytesIO()
                save_kwargs = {}
                if output_format == 'JPEG':
                    save_kwargs = {'quality': quality, 'optimize': True}
                elif output_format == 'WEBP':
                    save_kwargs = {'quality': quality, 'method': 4}
                elif output_format == 'PNG':
                    save_kwargs = {'optimize': True}
                
                img.save(buffer, format=output_format, **save_kwargs)
                resized_bytes = buffer.getvalue()
                
                # Cache the result
                self._resize_cache[file_id] = resized_bytes
                logger.debug(f"Resized image {file_id}: {len(resized_bytes)} bytes")
                
                return resized_bytes
                
        except Exception as e:
            logger.error(f"Failed to resize image {image_path}: {e}")
            # Fallback: return original image bytes
            with open(image_path, "rb") as f:
                return f.read()
    
    async def _call_vision_model(
        self, 
        backend: str, 
        model: str, 
        image_path: Path, 
        prompt: str,
        file_id: Optional[str] = None,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Call vision model to generate caption."""
        # Resize image for vision model (with caching)
        if file_id:
            image_bytes = self._resize_image_for_vision(image_path, file_id)
        else:
            # Single caption generation (not a job), resize without caching
            image_bytes = self._resize_image_for_vision(image_path, str(image_path))
        
        # Encode to base64
        image_data = base64.b64encode(image_bytes).decode("utf-8")
        
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=self.settings.vision.timeout_seconds)
        
        if backend == "lmstudio":
            return await self._call_lmstudio(model, image_data, prompt, timeout, seed=seed)
        else:
            raise ValueError(f"Unknown or unsupported backend: {backend}")
    
    async def _call_lmstudio(
        self, 
        model: str, 
        image_data: str, 
        prompt: str,
        timeout: "aiohttp.ClientTimeout",
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Call LM Studio API for caption generation."""
        url = f"{self.settings.vision.lmstudio_url}/v1/chat/completions"
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                        }
                    ]
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.7 if seed is not None else 0.3  # Higher temp with seed for more variation
        }
        
        if seed is not None:
            payload["seed"] = seed
            # Add unique identifier to bypass LM Studio caching
            import time
            payload["messages"][0]["content"][0]["text"] = f"[{seed}] " + prompt
            logger.info(f"Using seed {seed} for LM Studio API call (temp=0.7)")
        else:
            logger.info("No seed provided, LM Studio will use random generation (temp=0.3)")


        
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ValueError(f"LM Studio API error: {resp.status} - {error_text}")
                
                data = await resp.json()
                response_text = data["choices"][0]["message"]["content"]
        
        return self._parse_caption_response(response_text)
    
    async def _call_lmstudio_text(self, model: str, prompt: str) -> str:
        """Call LM Studio API for text-only generation (no image)."""
        import aiohttp
        url = f"{self.settings.vision.lmstudio_url}/v1/chat/completions"
        timeout = aiohttp.ClientTimeout(total=self.settings.vision.timeout_seconds)
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.3
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ValueError(f"LM Studio API error: {resp.status} - {error_text}")
                
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    
    def _build_creative_prompt(
        self,
        style: str,
        max_length: Optional[int] = None,
        custom_prompt: Optional[str] = None,
        trigger_phrase: Optional[str] = None,
        template_id: Optional[str] = None
    ) -> str:
        """Build the creative part of the prompt (user-customizable)."""
        # 1. Check for predefined templates first
        if template_id and template_id in PROMPT_TEMPLATES:
            logger.info(f"Using prompt template: {template_id}")
            creative = PROMPT_TEMPLATES[template_id]
            
            # Special case for refine - append original text if it's in custom_prompt
            if template_id == "refine" and custom_prompt:
                creative += f"\n\nUser prompt to refine:\n{custom_prompt}"
            elif template_id == "refine":
                logger.warning("Template 'refine' selected but no custom_prompt (text to refine) provided.")
            
        # 2. Use custom prompt if provided (and not handled by template)
        elif custom_prompt:
            logger.info(f"Using custom prompt ({len(custom_prompt)} chars)")
            creative = custom_prompt
        else:
            # 3. Build standard prompt based on style (legacy/default behavior)
            if style == "custom":
                logger.warning(f"Style is 'custom' but no custom_prompt provided! Falling back to natural.")
                style = "natural"
            
            prompts = {
                "natural": "Describe this image in one clear, concise sentence suitable for AI image generation training.\nFocus on: main subject, action/pose, setting/background.\nBe objective and descriptive. Avoid subjective interpretations.",
                "detailed": "Provide a detailed 2-3 sentence description of this image suitable for AI training.\nInclude: subjects, actions, environment, mood, lighting, notable details, composition.\nBe specific and objective.",
                "tags": "Generate 15-25 comma-separated lowercase tags describing this image. NOT a sentence - just tags separated by commas.\nInclude: subject, gender, pose/action, clothing details, hair color/style, eye color, background/setting, lighting, colors, mood."
            }
            creative = prompts.get(style, prompts["natural"])
        
        # Add trigger phrase instructions if provided
        if trigger_phrase:
            if style == "tags" or (custom_prompt and "tag" in custom_prompt.lower()):
                # Tags format - trigger phrase as first tag
                trigger_instruction = f'\n\nIMPORTANT: The caption MUST start with "{trigger_phrase}" as the first tag.\nExample: "{trigger_phrase}, woman, brown hair, white dress, studio, soft lighting"'
            else:
                # Sentence format - trigger phrase at beginning
                trigger_instruction = f'\n\nIMPORTANT: The caption MUST begin with "{trigger_phrase}" followed by a description of the image.'
            creative += trigger_instruction
        
        # Add length constraint if specified
        if max_length:
            creative += f"\n\nMaximum length: {max_length} characters."
        
        return creative
    
    def _build_output_directive(self) -> str:
        """Build the system output directive (enforced by system, not user-editable)."""
        return """\n\nAlso assess the image quality for training suitability.

Output format (JSON only, no other text):
{
  "caption": "Your English caption here",
  "caption_ru": "Russian translation of the caption",
  "quality": {
    "sharpness": 0.0-1.0,
    "clarity": 0.0-1.0,
    "composition": 0.0-1.0,
    "exposure": 0.0-1.0,
    "overall": 0.0-1.0
  },
  "flags": ["list", "of", "any", "quality", "issues"]
}"""
    
    def _build_prompt(
        self, 
        style: str, 
        max_length: Optional[int] = None,
        custom_prompt: Optional[str] = None,
        trigger_phrase: Optional[str] = None,
        template_id: Optional[str] = None
    ) -> str:
        """Build the complete prompt for caption generation."""
        logger.debug(f"_build_prompt called: style={style}, template_id={template_id}, custom_prompt={custom_prompt[:50] if custom_prompt else None}...")
        
        # Build creative part (user-customizable)
        creative_prompt = self._build_creative_prompt(style, max_length, custom_prompt, trigger_phrase, template_id)
        
        # Append system output directive (always enforced)
        output_directive = self._build_output_directive()
        
        return creative_prompt + output_directive
    
    def _parse_caption_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the caption response from the model."""
        response_text = response_text.strip()
        logger.debug(f"Raw vision model response ({len(response_text)} chars): {response_text[:500]}")
        
        # Try to extract JSON from the response
        # Models sometimes wrap JSON in markdown code blocks
        json_text = response_text
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            if end > start:
                json_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            if end > start:
                json_text = response_text[start:end].strip()
        
        logger.debug(f"Extracted JSON text: {json_text[:300]}")
        
        # Try to parse as JSON
        try:
            data = json.loads(json_text)
            logger.debug(f"Parsed JSON data: {data}")
            if isinstance(data, dict) and "caption" in data:
                quality = data.get("quality", {})
                overall_score = quality.get("overall") if isinstance(quality, dict) else None
                flags = data.get("flags", [])
                
                # If quality is a dict, extract all scores for quality_flags
                quality_details = None
                if isinstance(quality, dict):
                    quality_details = [f"{k}:{v}" for k, v in quality.items() if k != "overall"]
                
                caption_text = data["caption"]
                logger.debug(f"Extracted caption: '{caption_text}'")
                
                return {
                    "caption": caption_text,
                    "caption_ru": data.get("caption_ru", ""),
                    "quality_score": overall_score,
                    "quality_flags": flags if flags else quality_details
                }
        except json.JSONDecodeError as e:
            logger.debug(f"JSON parse failed: {e}")
            pass
        
        # Fallback: treat the whole response as the caption
        caption = response_text
        
        # Remove common prefixes that models sometimes add
        prefixes_to_remove = [
            "Caption:", "Description:", "Here is", "The image shows",
            "This image shows", "In this image,", "Here's"
        ]
        for prefix in prefixes_to_remove:
            if caption.lower().startswith(prefix.lower()):
                caption = caption[len(prefix):].strip()
        
        # Remove quotes if wrapped
        if caption.startswith('"') and caption.endswith('"'):
            caption = caption[1:-1]
        
        return {
            "caption": caption,
            "caption_ru": None,
            "quality_score": None,
            "quality_flags": None
        }
