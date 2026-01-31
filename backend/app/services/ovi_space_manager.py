"""
Ovi Space Lifecycle Manager

Manages the HuggingFace Space lifecycle for cost-effective video generation:
- Start/restart sleeping spaces
- Wait for full initialization
- Health check before use
- Automatic shutdown after completion

The space has a 5-minute inactivity timeout, so we need to manage its lifecycle
to minimize GPU costs while ensuring reliable video generation.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Callable, Any

from huggingface_hub import HfApi
from gradio_client import Client, handle_file

from app.config import settings
from app.exceptions import VideoGenerationError

logger = logging.getLogger(__name__)


class SpaceStatus(str, Enum):
    """HuggingFace Space runtime stages."""
    RUNNING = "RUNNING"
    BUILDING = "BUILDING"
    SLEEPING = "SLEEPING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class SpaceHealth:
    """Space health check result."""
    status: SpaceStatus
    is_ready: bool
    api_responsive: bool
    error_message: Optional[str] = None


class OviSpaceManager:
    """
    Manages Ovi HuggingFace Space lifecycle for video generation.
    
    Usage:
        # As context manager (recommended)
        async with OviSpaceManager() as ovi:
            for scene in scenes:
                video = await ovi.generate_video(scene.image, scene.prompt)
        # Space automatically shuts down
        
        # Manual management
        manager = OviSpaceManager()
        await manager.ensure_running()
        videos = await manager.generate_videos(scenes)
        await manager.shutdown()
    """

    DEFAULT_STARTUP_TIMEOUT_MINUTES = 5
    DEFAULT_HEALTH_CHECK_RETRIES = 3
    POLL_INTERVAL_SECONDS = 10
    
    # Quality presets (sample_steps)
    QUALITY_PRESETS = {
        "draft": 15,
        "standard": 30,
        "high": 50,
        "ultra": 75,
    }

    def __init__(
        self,
        space_id: Optional[str] = None,
        token: Optional[str] = None,
        quality: str = "standard",
        auto_shutdown: bool = True,
    ):
        """
        Initialize the Ovi Space Manager.
        
        Args:
            space_id: HuggingFace space ID (default from settings)
            token: HuggingFace API token (default from settings)
            quality: Video quality preset (draft/standard/high/ultra)
            auto_shutdown: Whether to pause space after completion
        """
        self.space_id = space_id or settings.OVI_SPACE
        self.token = token or settings.HUGGINGFACE_TOKEN
        self.quality = quality
        self.sample_steps = self.QUALITY_PRESETS.get(quality, 30)
        self.auto_shutdown = auto_shutdown
        
        self._hf_api: Optional[HfApi] = None
        self._gradio_client: Optional[Client] = None
        self._session_started = False

    @property
    def hf_api(self) -> HfApi:
        """Lazy initialization of HuggingFace API client."""
        if self._hf_api is None:
            self._hf_api = HfApi(token=self.token)
        return self._hf_api

    @property
    def gradio_client(self) -> Client:
        """Lazy initialization of Gradio client."""
        if self._gradio_client is None:
            logger.info(f"Connecting to Ovi space: {self.space_id}")
            self._gradio_client = Client(self.space_id, token=self.token)
        return self._gradio_client

    def _reset_client(self) -> None:
        """Reset Gradio client (needed after space restart)."""
        self._gradio_client = None
        self._session_started = False

    # =========================================================================
    # Space Status Management
    # =========================================================================

    def get_status(self) -> SpaceStatus:
        """
        Get current space runtime status.
        
        Returns:
            SpaceStatus enum value
        """
        try:
            info = self.hf_api.space_info(self.space_id)
            stage = info.runtime.stage if info.runtime else "UNKNOWN"
            return SpaceStatus(stage) if stage in SpaceStatus.__members__ else SpaceStatus.UNKNOWN
        except Exception as e:
            logger.error(f"Failed to get space status: {e}")
            return SpaceStatus.ERROR

    def start_space(self) -> bool:
        """
        Start or restart the space.
        
        Returns:
            True if restart command was sent successfully
        """
        try:
            logger.info(f"Starting space: {self.space_id}")
            self.hf_api.restart_space(self.space_id)
            self._reset_client()
            return True
        except Exception as e:
            logger.error(f"Failed to start space: {e}")
            return False

    def pause_space(self) -> bool:
        """
        Pause the space to stop GPU billing.
        
        Returns:
            True if pause command was sent successfully
        """
        try:
            logger.info(f"Pausing space: {self.space_id}")
            self.hf_api.pause_space(self.space_id)
            return True
        except Exception as e:
            logger.error(f"Failed to pause space: {e}")
            return False

    async def wait_for_ready(
        self,
        timeout_minutes: int = DEFAULT_STARTUP_TIMEOUT_MINUTES,
        on_status_change: Optional[Callable[[SpaceStatus], None]] = None,
    ) -> bool:
        """
        Wait for space to be fully running.
        
        Args:
            timeout_minutes: Maximum time to wait
            on_status_change: Optional callback for status updates
            
        Returns:
            True if space is running, False if timeout
        """
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        last_status = None
        
        logger.info(f"Waiting for space to be ready (timeout: {timeout_minutes}m)...")
        
        while (time.time() - start_time) < timeout_seconds:
            status = self.get_status()
            
            if status != last_status:
                logger.info(f"Space status: {status.value}")
                if on_status_change:
                    on_status_change(status)
                last_status = status
            
            if status == SpaceStatus.RUNNING:
                logger.info("Space is running!")
                return True
            elif status == SpaceStatus.ERROR:
                logger.error("Space is in error state")
                return False
            
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
        
        logger.error(f"Timeout waiting for space after {timeout_minutes} minutes")
        return False

    def verify_healthy(self) -> SpaceHealth:
        """
        Verify space is healthy and API is responsive.
        
        Makes a lightweight API call to confirm the space is truly ready.
        Sometimes status is RUNNING but models are still loading.
        
        Returns:
            SpaceHealth with detailed status
        """
        status = self.get_status()
        
        if status != SpaceStatus.RUNNING:
            return SpaceHealth(
                status=status,
                is_ready=False,
                api_responsive=False,
                error_message=f"Space not running: {status.value}"
            )
        
        try:
            # Try to view API info - lightweight check
            self.gradio_client.view_api(print_info=False)
            
            # Try to start a session
            if not self._session_started:
                self.gradio_client.predict(api_name="/start_session")
                self._session_started = True
            
            return SpaceHealth(
                status=status,
                is_ready=True,
                api_responsive=True,
            )
        except Exception as e:
            return SpaceHealth(
                status=status,
                is_ready=False,
                api_responsive=False,
                error_message=str(e)
            )

    # =========================================================================
    # High-Level Operations
    # =========================================================================

    async def ensure_running(
        self,
        timeout_minutes: int = DEFAULT_STARTUP_TIMEOUT_MINUTES,
        max_retries: int = 3,
    ) -> bool:
        """
        Ensure space is running and healthy.
        
        Will start space if needed and wait for it to be ready.
        
        Args:
            timeout_minutes: Time to wait for startup
            max_retries: Number of restart attempts if space fails
            
        Returns:
            True if space is ready for video generation
        """
        for attempt in range(max_retries):
            status = self.get_status()
            logger.info(f"Space status check (attempt {attempt + 1}/{max_retries}): {status.value}")
            
            if status == SpaceStatus.RUNNING:
                # Verify it's actually healthy
                health = self.verify_healthy()
                if health.is_ready:
                    logger.info("Space is ready for video generation")
                    return True
                else:
                    logger.warning(f"Space running but not healthy: {health.error_message}")
                    # Try restarting
                    self.start_space()
            
            elif status in (SpaceStatus.SLEEPING, SpaceStatus.PAUSED, SpaceStatus.STOPPED):
                logger.info(f"Space is {status.value}, starting...")
                self.start_space()
            
            elif status == SpaceStatus.BUILDING:
                logger.info("Space is building, waiting...")
            
            elif status == SpaceStatus.ERROR:
                logger.warning("Space in error state, attempting restart...")
                self.start_space()
            
            # Wait for ready
            if await self.wait_for_ready(timeout_minutes):
                health = self.verify_healthy()
                if health.is_ready:
                    return True
                logger.warning(f"Space ready but health check failed: {health.error_message}")
            
            # Exponential backoff before retry
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 30
                logger.info(f"Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
        
        logger.error(f"Failed to get space running after {max_retries} attempts")
        return False

    async def shutdown(self) -> bool:
        """
        Shutdown the space to stop GPU billing.
        
        Returns:
            True if space was paused successfully
        """
        if self.auto_shutdown:
            logger.info("Shutting down space to save costs...")
            return self.pause_space()
        else:
            logger.info("Auto-shutdown disabled, leaving space running")
            return True

    # =========================================================================
    # Video Generation
    # =========================================================================

    def _generate_video_sync(
        self,
        image_path: str,
        prompt: str,
    ) -> str:
        """Synchronous video generation (for executor)."""
        result = self.gradio_client.predict(
            text_prompt=prompt,
            sample_steps=self.sample_steps,
            image=handle_file(image_path),
            api_name="/generate_scene",
        )
        
        if isinstance(result, dict):
            return result.get('video', result)
        return result

    async def generate_video(
        self,
        image_path: str,
        prompt: str,
    ) -> str:
        """
        Generate a single video from image and prompt.
        
        Args:
            image_path: Path to source image
            prompt: Text prompt with Ovi tokens (<S>...<E>, <AUDCAP>...<ENDAUDCAP>)
            
        Returns:
            Path to generated video file
        """
        logger.info(f"Generating video from: {image_path}")
        logger.debug(f"Prompt: {prompt}")
        
        start_time = time.time()
        
        video_path = await asyncio.get_event_loop().run_in_executor(
            None,
            self._generate_video_sync,
            image_path,
            prompt,
        )
        
        elapsed = time.time() - start_time
        logger.info(f"Video generated in {elapsed:.1f}s: {video_path}")
        
        return video_path

    async def generate_videos(
        self,
        scenes: List[dict],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[str]:
        """
        Generate videos for multiple scenes.
        
        Args:
            scenes: List of dicts with 'image_path' and 'prompt' keys
            on_progress: Optional callback(completed, total) for progress updates
            
        Returns:
            List of generated video paths
        """
        total = len(scenes)
        videos = []
        
        logger.info(f"Generating {total} videos...")
        
        for i, scene in enumerate(scenes):
            try:
                video_path = await self.generate_video(
                    scene['image_path'],
                    scene['prompt'],
                )
                videos.append(video_path)
                
                if on_progress:
                    on_progress(i + 1, total)
                    
            except Exception as e:
                logger.error(f"Scene {i + 1} failed: {e}")
                videos.append(None)
        
        successful = sum(1 for v in videos if v)
        logger.info(f"Generated {successful}/{total} videos successfully")
        
        return videos

    # =========================================================================
    # Context Manager Support
    # =========================================================================

    async def __aenter__(self) -> "OviSpaceManager":
        """Async context manager entry: ensure space is running."""
        success = await self.ensure_running()
        if not success:
            raise VideoGenerationError("Failed to start Ovi space")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit: shutdown space."""
        await self.shutdown()


# =============================================================================
# Convenience Functions
# =============================================================================

async def generate_episode_videos(
    scenes: List[dict],
    quality: str = "standard",
    auto_shutdown: bool = True,
) -> List[str]:
    """
    High-level function to generate all videos for an episode.
    
    Handles full lifecycle: start space → generate videos → shutdown.
    
    Args:
        scenes: List of scene dicts with 'image_path' and 'prompt'
        quality: Video quality (draft/standard/high/ultra)
        auto_shutdown: Pause space after completion
        
    Returns:
        List of generated video paths
    """
    async with OviSpaceManager(quality=quality, auto_shutdown=auto_shutdown) as manager:
        return await manager.generate_videos(scenes)
