"""Vision model integration service for auto-captioning."""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, AsyncGenerator

import aiohttp
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
        "ollama_name": "qwen2.5-vl:7b",
        "lmstudio_name": "qwen/qwen2.5-vl-7b-instruct",
        "vram_gb": 8.0,
        "description": "Excellent quality, good speed. Recommended for most users."
    },
    {
        "model_id": "qwen2.5-vl-3b",
        "name": "Qwen2.5-VL 3B",
        "ollama_name": "qwen2.5-vl:3b",
        "lmstudio_name": "qwen/qwen2.5-vl-3b-instruct",
        "vram_gb": 4.0,
        "description": "Fast and lightweight. Good for quick iterations."
    },
    {
        "model_id": "llava-1.6-34b",
        "name": "LLaVA 1.6 34B",
        "ollama_name": "llava:34b",
        "lmstudio_name": "liuhaotian/llava-v1.6-34b",
        "vram_gb": 24.0,
        "description": "Highest quality, requires significant VRAM."
    },
    {
        "model_id": "llava-1.6-13b",
        "name": "LLaVA 1.6 13B",
        "ollama_name": "llava:13b",
        "lmstudio_name": "liuhaotian/llava-v1.6-13b",
        "vram_gb": 12.0,
        "description": "Good balance of quality and speed."
    },
    {
        "model_id": "llava-1.6-7b",
        "name": "LLaVA 1.6 7B",
        "ollama_name": "llava:7b",
        "lmstudio_name": "liuhaotian/llava-v1.6-7b",
        "vram_gb": 6.0,
        "description": "Efficient option for lower VRAM systems."
    },
]


class VisionService:
    """Service for vision model integration and auto-captioning."""
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self._active_jobs: Dict[str, bool] = {}  # job_id -> is_paused
    
    async def list_models(self) -> List[VisionModelInfo]:
        """List available vision models."""
        models = []
        
        for model in CURATED_MODELS:
            # Check availability in configured backend
            backend = self.settings.vision.backend
            backend_name = model["ollama_name"] if backend == "ollama" else model["lmstudio_name"]
            
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
    
    async def generate_caption(
        self,
        file_id: str,
        style: str = "natural",
        max_length: Optional[int] = None,
        vision_model: Optional[str] = None,
        vision_backend: Optional[str] = None,
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
        prompt = self._build_prompt(style, max_length, custom_prompt, trigger_phrase)
        logger.debug(f"Vision prompt for style '{style}': {prompt[:200]}...")
        
        # Generate caption
        start_time = time.time()
        result = await self._call_vision_model(backend, model, file_path, prompt)
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
            backend=backend
        )
    
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
    
    async def start_auto_caption_job(
        self,
        caption_set_id: str,
        vision_model: Optional[str] = None,
        vision_backend: Optional[str] = None,
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
            cs_max_length = caption_set.max_length
            cs_custom_prompt = caption_set.custom_prompt
            cs_trigger_phrase = caption_set.trigger_phrase
            cs_dataset_id = caption_set.dataset_id
            
            logger.info(f"Caption job {job_id}: style={cs_style}, custom_prompt={'yes (' + str(len(cs_custom_prompt)) + ' chars)' if cs_custom_prompt else 'no'}, trigger={cs_trigger_phrase}")
            
            # Get file IDs to process (just the IDs, not full objects)
            from ..models import DatasetFile
            
            # Count existing captions to sync completed_files counter (important for resume)
            existing_caption_count = self.db.query(Caption).filter(
                Caption.caption_set_id == caption_set_id
            ).count()
            
            # Update job's completed count to match actual captions (handles resume)
            job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
            if job:
                job.completed_files = existing_caption_count
                self.db.commit()
            
            existing_caption_file_ids = self.db.query(Caption.file_id).filter(
                Caption.caption_set_id == caption_set_id
            ).subquery()
            
            file_ids_to_process = self.db.query(DatasetFile.file_id).filter(
                DatasetFile.dataset_id == cs_dataset_id,
                DatasetFile.excluded == False,
                ~DatasetFile.file_id.in_(existing_caption_file_ids)
            ).all()
            
            # Extract just the IDs as a list
            file_ids = [f[0] for f in file_ids_to_process]
            
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
                        custom_prompt=cs_custom_prompt,
                        trigger_phrase=cs_trigger_phrase
                    )
                    
                    # Re-fetch job after async operation
                    job = self.db.query(CaptionJob).filter(CaptionJob.id == job_id).first()
                    if not job:
                        break
                    
                    # Save caption
                    caption = Caption(
                        caption_set_id=job.caption_set_id,
                        file_id=file_id,
                        text=result.caption,
                        source="generated",
                        vision_model=job.vision_model,
                        quality_score=result.quality_score,
                        quality_flags=json.dumps(result.quality_flags) if result.quality_flags else None
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
                    
                    job.completed_files += 1
                    logger.debug(f"Caption job {job_id}: completed {job.completed_files}/{len(file_ids)} files")
                    
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
            self.db.commit()
    
    async def _check_model_available(self, backend: str, model_name: str) -> bool:
        """Check if a model is available in the backend."""
        try:
            if backend == "ollama":
                url = f"{self.settings.vision.ollama_url}/api/tags"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            models = [m["name"] for m in data.get("models", [])]
                            return model_name in models
            elif backend == "lmstudio":
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
    
    async def _call_vision_model(
        self, 
        backend: str, 
        model: str, 
        image_path: Path, 
        prompt: str
    ) -> Dict[str, Any]:
        """Call vision model to generate caption."""
        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        timeout = aiohttp.ClientTimeout(total=self.settings.vision.timeout_seconds)
        
        if backend == "ollama":
            return await self._call_ollama(model, image_data, prompt, timeout)
        elif backend == "lmstudio":
            return await self._call_lmstudio(model, image_data, prompt, timeout)
        else:
            raise ValueError(f"Unknown backend: {backend}")
    
    async def _call_ollama(
        self, 
        model: str, 
        image_data: str, 
        prompt: str,
        timeout: aiohttp.ClientTimeout
    ) -> Dict[str, Any]:
        """Call Ollama API for caption generation using chat endpoint."""
        # Use chat endpoint which properly supports think=false per Ollama docs
        url = f"{self.settings.vision.ollama_url}/api/chat"
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_data]
                }
            ],
            "stream": False,
            "think": False,  # Request no thinking (may be ignored by some models)
            "options": {
                "temperature": 0.3,
                "num_predict": self.settings.vision.max_tokens  # Configurable in settings
            }
        }
        
        logger.debug(f"Ollama chat request with think=False for model: {model}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ValueError(f"Ollama API error: {resp.status} - {error_text}")
                
                data = await resp.json()
                logger.debug(f"Ollama full response: {data}")
                
                # Extract response from chat format
                message = data.get("message", {})
                response_text = message.get("content", "")
                thinking = message.get("thinking", "")
                
                # Check for thinking mode issue - model used all tokens thinking
                if not response_text and data.get("done_reason") == "length":
                    if thinking:
                        logger.warning(f"Model exhausted tokens during thinking phase despite think=false. Model may not support disabling thinking.")
                        raise ValueError("Model exhausted tokens during thinking phase. Try a different model.")
                
                # Log if thinking occurred anyway (for debugging)
                if thinking:
                    logger.debug(f"Model produced thinking output ({len(thinking)} chars) despite think=False")
                
                # Check for other empty response issues
                if not response_text and data.get("done") and data.get("total_duration"):
                    logger.warning(f"Ollama returned empty response but reported done. Full data: {data}")
        
        return self._parse_caption_response(response_text)
    
    async def _call_lmstudio(
        self, 
        model: str, 
        image_data: str, 
        prompt: str,
        timeout: aiohttp.ClientTimeout
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
            "temperature": 0.3
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ValueError(f"LM Studio API error: {resp.status} - {error_text}")
                
                data = await resp.json()
                response_text = data["choices"][0]["message"]["content"]
        
        return self._parse_caption_response(response_text)
    
    def _build_prompt(
        self, 
        style: str, 
        max_length: Optional[int] = None,
        custom_prompt: Optional[str] = None,
        trigger_phrase: Optional[str] = None
    ) -> str:
        """Build the prompt for caption generation."""
        logger.debug(f"_build_prompt called: style={style}, custom_prompt={custom_prompt[:50] if custom_prompt else None}...")
        
        if custom_prompt:
            logger.info(f"Using custom prompt ({len(custom_prompt)} chars)")
            return custom_prompt
        
        if style == "custom":
            logger.warning(f"Style is 'custom' but no custom_prompt provided! Falling back to natural.")
        
        length_constraint = f"Maximum length: {max_length} characters. " if max_length else ""
        
        # For tags style, we need a different trigger instruction format
        if trigger_phrase:
            tags_trigger_instruction = f'IMPORTANT: The caption MUST start with "{trigger_phrase}" as the first tag.\n'
            sentence_trigger_instruction = f'IMPORTANT: The caption MUST begin with "{trigger_phrase}" followed by a description of the image.\n'
        else:
            tags_trigger_instruction = ""
            sentence_trigger_instruction = ""
        
        quality_json = """{
  "caption": "Your caption here",
  "quality": {
    "sharpness": 0.0-1.0,
    "clarity": 0.0-1.0,
    "composition": 0.0-1.0,
    "exposure": 0.0-1.0,
    "overall": 0.0-1.0
  },
  "flags": ["list", "of", "any", "quality", "issues"]
}"""
        
        # Example for tags with trigger phrase
        tags_example = f'Example: "{trigger_phrase}, woman, brown hair, white dress, studio, soft lighting"' if trigger_phrase else 'Example: "woman, brown hair, white dress, studio, soft lighting"'
        
        prompts = {
            "natural": f"""{sentence_trigger_instruction}Describe this image in one clear, concise sentence suitable for AI image generation training.
Focus on: main subject, action/pose, setting/background.
Be objective and descriptive. Avoid subjective interpretations.
{length_constraint}
Also assess the image quality for training suitability.

Output format (JSON only, no other text):
{quality_json}""",

            "detailed": f"""{sentence_trigger_instruction}Provide a detailed 2-3 sentence description of this image suitable for AI training.
Include: subjects, actions, environment, mood, lighting, notable details, composition.
Be specific and objective.
{length_constraint}
Also assess the image quality for training suitability.

Output format (JSON only, no other text):
{quality_json}""",

            "tags": f"""{tags_trigger_instruction}Generate 15-25 comma-separated lowercase tags describing this image. NOT a sentence - just tags separated by commas.
{tags_example}
Include: subject, gender, pose/action, clothing details, hair color/style, eye color, background/setting, lighting, colors, mood.
{length_constraint}
Also assess the image quality for training suitability.

Output format (JSON only, no other text):
{quality_json}"""
        }
        
        return prompts.get(style, prompts["natural"])
    
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
            "quality_score": None,
            "quality_flags": None
        }
