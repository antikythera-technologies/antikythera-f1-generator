"""
RunPod Pod Lifecycle Manager for Ovi Video Generation

Manages a self-hosted Ovi instance on a RunPod GPU pod:
- Resume stopped/exited pods
- Wait for Ovi Gradio server to be ready (model load ~4-5 min)
- Health check before use
- Automatic pod stop after completion to stop GPU billing

Replaces the previous HuggingFace Space manager after migrating to RunPod.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Callable

import httpx
from gradio_client import Client, handle_file

from app.config import settings
from app.exceptions import VideoGenerationError

logger = logging.getLogger(__name__)

RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


class PodStatus(str, Enum):
    """RunPod pod status values."""
    RUNNING = "RUNNING"
    EXITED = "EXITED"
    CREATED = "CREATED"
    RESTARTING = "RESTARTING"
    UNKNOWN = "UNKNOWN"


# Backward-compatible alias
SpaceStatus = PodStatus


@dataclass
class PodHealth:
    """Pod health check result."""
    status: PodStatus
    is_ready: bool
    api_responsive: bool
    error_message: Optional[str] = None


# Backward-compatible alias
SpaceHealth = PodHealth


class RunPodManager:
    """
    Manages Ovi RunPod GPU pod lifecycle for video generation.

    Communicates with the RunPod GraphQL API to resume/stop the pod,
    then uses a Gradio client to talk to the Ovi server running on the pod.

    Usage:
        # As context manager (recommended)
        async with RunPodManager() as ovi:
            for scene in scenes:
                video = await ovi.generate_video(scene.image, scene.prompt)
        # Pod automatically stopped

        # Manual management
        manager = RunPodManager()
        await manager.ensure_running()
        videos = await manager.generate_videos(scenes)
        await manager.shutdown()
    """

    DEFAULT_STARTUP_TIMEOUT_MINUTES = 8
    DEFAULT_HEALTH_CHECK_RETRIES = 3
    POD_POLL_INTERVAL_SECONDS = 10
    GRADIO_POLL_INTERVAL_SECONDS = 15
    GRADIO_READY_TIMEOUT_MINUTES = 6  # Model load takes ~4-5 min

    # Quality presets: (sample_steps, image_conditioning, denoise, guidance)
    # Lower steps + higher conditioning + lower denoise = better style preservation
    QUALITY_PRESETS = {
        "draft": {"steps": 10, "conditioning": 0.90, "denoise": 0.40, "guidance": 1.5},
        "standard": {"steps": 20, "conditioning": 0.85, "denoise": 0.55, "guidance": 2.0},
        "high": {"steps": 30, "conditioning": 0.80, "denoise": 0.60, "guidance": 2.5},
        "ultra": {"steps": 40, "conditioning": 0.75, "denoise": 0.65, "guidance": 3.0},
        "caricature": {"steps": 15, "conditioning": 0.92, "denoise": 0.35, "guidance": 1.5},
    }

    # GraphQL queries and mutations
    _QUERY_POD = """
    query Pod($podId: String!) {
        pod(input: { podId: $podId }) {
            id
            name
            desiredStatus
            runtime {
                uptimeInSeconds
                ports {
                    ip
                    isIpPublic
                    privatePort
                    publicPort
                    type
                }
            }
        }
    }
    """

    _MUTATION_RESUME = """
    mutation ResumePod($podId: String!, $gpuCount: Int!) {
        podResume(input: { podId: $podId, gpuCount: $gpuCount }) {
            id
            desiredStatus
            costPerHr
        }
    }
    """

    _MUTATION_STOP = """
    mutation StopPod($podId: String!) {
        podStop(input: { podId: $podId }) {
            id
            desiredStatus
        }
    }
    """

    def __init__(
        self,
        pod_id: Optional[str] = None,
        api_key: Optional[str] = None,
        server_url: Optional[str] = None,
        quality: str = "standard",
        auto_shutdown: bool = True,
        gpu_count: int = 1,
    ):
        """
        Initialize the RunPod Manager.

        Args:
            pod_id: RunPod pod ID (default from settings)
            api_key: RunPod API key (default from settings)
            server_url: Ovi Gradio server URL (default from settings)
            quality: Video quality preset (draft/standard/high/ultra)
            auto_shutdown: Whether to stop the pod after completion
            gpu_count: Number of GPUs to request when resuming
        """
        self.pod_id = pod_id or settings.RUNPOD_POD_ID
        self.api_key = api_key or settings.RUNPOD_API_KEY
        self.server_url = server_url or settings.OVI_SERVER_URL
        self.quality = quality
        self.auto_shutdown = auto_shutdown
        self.gpu_count = gpu_count

        # Load style-preservation parameters from preset
        preset = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS["standard"])
        self.sample_steps = preset["steps"]
        self.image_conditioning_strength = preset["conditioning"]
        self.denoise_strength = preset["denoise"]
        self.guidance_scale = preset["guidance"]

        # Allow env-level overrides
        if settings.OVI_IMAGE_CONDITIONING_STRENGTH != 0.85:
            self.image_conditioning_strength = settings.OVI_IMAGE_CONDITIONING_STRENGTH
        if settings.OVI_DENOISE_STRENGTH != 0.55:
            self.denoise_strength = settings.OVI_DENOISE_STRENGTH
        if settings.OVI_GUIDANCE_SCALE != 2.0:
            self.guidance_scale = settings.OVI_GUIDANCE_SCALE

        self._http_client: Optional[httpx.AsyncClient] = None
        self._gradio_client: Optional[Client] = None
        self._session_started = False

    # =========================================================================
    # HTTP / GraphQL Helpers
    # =========================================================================

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy initialization of async HTTP client for RunPod API."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._http_client

    async def _graphql(self, query: str, variables: Optional[dict] = None) -> dict:
        """
        Execute a RunPod GraphQL request.

        Args:
            query: GraphQL query or mutation string
            variables: Optional query variables

        Returns:
            The 'data' portion of the GraphQL response

        Raises:
            VideoGenerationError: If the request fails or returns errors
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self.http_client.post(RUNPOD_GRAPHQL_URL, json=payload)
            response.raise_for_status()
            result = response.json()

            if "errors" in result:
                error_msg = result["errors"][0].get("message", "Unknown GraphQL error")
                raise VideoGenerationError(f"RunPod API error: {error_msg}")

            return result.get("data", {})

        except httpx.HTTPError as e:
            raise VideoGenerationError(f"RunPod API request failed: {e}") from e

    @property
    def gradio_client(self) -> Client:
        """Lazy initialization of Gradio client pointing at the RunPod proxy URL."""
        if self._gradio_client is None:
            logger.info(f"Connecting Gradio client to: {self.server_url}")
            self._gradio_client = Client(self.server_url)
        return self._gradio_client

    def _reset_client(self) -> None:
        """Reset Gradio client (needed after pod restart)."""
        self._gradio_client = None
        self._session_started = False

    # =========================================================================
    # Pod Status Management
    # =========================================================================

    async def get_status(self) -> PodStatus:
        """
        Get current pod status from RunPod API.

        Returns:
            PodStatus enum value
        """
        try:
            data = await self._graphql(self._QUERY_POD, {"podId": self.pod_id})
            pod = data.get("pod")
            if pod is None:
                logger.error(f"Pod {self.pod_id} not found")
                return PodStatus.UNKNOWN

            desired = pod.get("desiredStatus", "UNKNOWN")
            try:
                return PodStatus(desired)
            except ValueError:
                logger.warning(f"Unknown pod status: {desired}")
                return PodStatus.UNKNOWN

        except VideoGenerationError:
            raise
        except Exception as e:
            logger.error(f"Failed to get pod status: {e}")
            return PodStatus.UNKNOWN

    async def resume_pod(self) -> bool:
        """
        Resume the pod (start it from stopped/exited state).

        Returns:
            True if resume command was sent successfully
        """
        try:
            logger.info(f"Resuming pod {self.pod_id} with {self.gpu_count} GPU(s)...")
            data = await self._graphql(
                self._MUTATION_RESUME,
                {"podId": self.pod_id, "gpuCount": self.gpu_count},
            )
            result = data.get("podResume", {})
            cost = result.get("costPerHr", "unknown")
            logger.info(f"Pod resume initiated. Cost: ${cost}/hr")
            self._reset_client()
            return True
        except Exception as e:
            logger.error(f"Failed to resume pod: {e}")
            return False

    async def stop_pod(self) -> bool:
        """
        Stop the pod to halt GPU billing.

        Returns:
            True if stop command was sent successfully
        """
        try:
            logger.info(f"Stopping pod {self.pod_id}...")
            await self._graphql(self._MUTATION_STOP, {"podId": self.pod_id})
            logger.info("Pod stop initiated")
            return True
        except Exception as e:
            logger.error(f"Failed to stop pod: {e}")
            return False

    async def wait_for_pod_running(
        self,
        timeout_minutes: int = DEFAULT_STARTUP_TIMEOUT_MINUTES,
        on_status_change: Optional[Callable[[PodStatus], None]] = None,
    ) -> bool:
        """
        Wait for the pod to reach RUNNING status.

        Args:
            timeout_minutes: Maximum time to wait
            on_status_change: Optional callback for status updates

        Returns:
            True if pod is running, False on timeout
        """
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        last_status = None

        logger.info(f"Waiting for pod to be running (timeout: {timeout_minutes}m)...")

        while (time.time() - start_time) < timeout_seconds:
            status = await self.get_status()

            if status != last_status:
                logger.info(f"Pod status: {status.value}")
                if on_status_change:
                    on_status_change(status)
                last_status = status

            if status == PodStatus.RUNNING:
                logger.info("Pod is running!")
                return True

            await asyncio.sleep(self.POD_POLL_INTERVAL_SECONDS)

        logger.error(f"Timeout waiting for pod after {timeout_minutes} minutes")
        return False

    async def wait_for_gradio_ready(
        self,
        timeout_minutes: float = GRADIO_READY_TIMEOUT_MINUTES,
    ) -> bool:
        """
        Wait for the Ovi Gradio server to respond on the pod.

        After a pod resumes, the Ovi model takes ~4-5 minutes to load into VRAM.
        This polls the Gradio API info endpoint until it responds.

        Args:
            timeout_minutes: Maximum time to wait for Gradio

        Returns:
            True if Gradio is responsive, False on timeout
        """
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        info_url = f"{self.server_url}/gradio_api/info"

        logger.info(
            f"Waiting for Ovi Gradio server at {info_url} "
            f"(timeout: {timeout_minutes}m, model load ~4-5 min)..."
        )

        while (time.time() - start_time) < timeout_seconds:
            try:
                response = await self.http_client.get(info_url, timeout=10.0)
                if response.status_code == 200:
                    elapsed = time.time() - start_time
                    logger.info(f"Ovi Gradio server is ready! (took {elapsed:.0f}s)")
                    return True
                else:
                    logger.debug(f"Gradio not ready yet (HTTP {response.status_code})")
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                logger.debug("Gradio not responding yet...")
            except Exception as e:
                logger.debug(f"Gradio health check error: {e}")

            await asyncio.sleep(self.GRADIO_POLL_INTERVAL_SECONDS)

        logger.error(
            f"Timeout waiting for Gradio server after {timeout_minutes} minutes"
        )
        return False

    async def verify_healthy(self) -> PodHealth:
        """
        Verify pod is healthy and the Gradio API is responsive.

        Returns:
            PodHealth with detailed status
        """
        status = await self.get_status()

        if status != PodStatus.RUNNING:
            return PodHealth(
                status=status,
                is_ready=False,
                api_responsive=False,
                error_message=f"Pod not running: {status.value}",
            )

        try:
            # Check Gradio API info endpoint
            info_url = f"{self.server_url}/gradio_api/info"
            response = await self.http_client.get(info_url, timeout=10.0)

            if response.status_code != 200:
                return PodHealth(
                    status=status,
                    is_ready=False,
                    api_responsive=False,
                    error_message=f"Gradio returned HTTP {response.status_code}",
                )

            # Connect the Gradio client and start a session
            if not self._session_started:
                self._reset_client()
                self.gradio_client.predict(api_name="/start_session")
                self._session_started = True

            return PodHealth(
                status=status,
                is_ready=True,
                api_responsive=True,
            )
        except Exception as e:
            return PodHealth(
                status=status,
                is_ready=False,
                api_responsive=False,
                error_message=str(e),
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
        Ensure the pod is running and the Ovi Gradio server is healthy.

        Will resume the pod if stopped/exited, wait for it to reach RUNNING,
        then wait for the Gradio server to finish loading the model.

        Args:
            timeout_minutes: Time to wait for pod startup
            max_retries: Number of resume attempts if pod fails

        Returns:
            True if pod and Ovi are ready for video generation
        """
        for attempt in range(max_retries):
            status = await self.get_status()
            logger.info(
                f"Pod status check (attempt {attempt + 1}/{max_retries}): {status.value}"
            )

            if status == PodStatus.RUNNING:
                # Pod is running; check if Gradio is also ready
                health = await self.verify_healthy()
                if health.is_ready:
                    logger.info("Pod and Ovi Gradio are ready for video generation")
                    return True
                else:
                    logger.warning(
                        f"Pod running but Gradio not ready: {health.error_message}"
                    )
                    # Wait for Gradio to come up (model still loading)
                    if await self.wait_for_gradio_ready():
                        health = await self.verify_healthy()
                        if health.is_ready:
                            return True
                    # If still not ready, try stopping and resuming
                    logger.warning("Gradio failed to become ready, restarting pod...")
                    await self.stop_pod()
                    await asyncio.sleep(10)

            elif status in (PodStatus.EXITED, PodStatus.CREATED):
                logger.info(f"Pod is {status.value}, resuming...")
                if not await self.resume_pod():
                    logger.error("Failed to send resume command")
                    if attempt < max_retries - 1:
                        await asyncio.sleep((attempt + 1) * 30)
                    continue

            elif status == PodStatus.UNKNOWN:
                logger.warning("Pod status unknown, attempting resume...")
                await self.resume_pod()

            # Wait for pod to reach RUNNING
            if await self.wait_for_pod_running(timeout_minutes):
                # Pod is running, now wait for Gradio/model to load
                if await self.wait_for_gradio_ready():
                    health = await self.verify_healthy()
                    if health.is_ready:
                        return True
                    logger.warning(
                        f"Gradio responded but health check failed: {health.error_message}"
                    )
                else:
                    logger.warning("Gradio did not become ready in time")

            # Exponential backoff before retry
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 30
                logger.info(f"Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        logger.error(
            f"Failed to get pod and Ovi running after {max_retries} attempts"
        )
        return False

    async def shutdown(self) -> bool:
        """
        Shutdown the pod to stop GPU billing.

        Returns:
            True if pod was stopped successfully
        """
        try:
            if self.auto_shutdown:
                logger.info("Stopping RunPod pod to save costs...")
                return await self.stop_pod()
            else:
                logger.info("Auto-shutdown disabled, leaving pod running")
                return True
        finally:
            # Always clean up the HTTP client
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None

    # =========================================================================
    # Video Generation
    # =========================================================================

    def _generate_video_sync(
        self,
        image_path: str,
        prompt: str,
    ) -> str:
        """Synchronous video generation with style-preservation parameters."""
        try:
            result = self.gradio_client.predict(
                text_prompt=prompt,
                sample_steps=self.sample_steps,
                image=handle_file(image_path),
                image_conditioning_strength=self.image_conditioning_strength,
                denoise_strength=self.denoise_strength,
                guidance_scale=self.guidance_scale,
                api_name="/generate_scene",
            )
        except TypeError:
            logger.warning(
                "Ovi does not support extended params, falling back to basic mode"
            )
            result = self.gradio_client.predict(
                text_prompt=prompt,
                sample_steps=self.sample_steps,
                image=handle_file(image_path),
                api_name="/generate_scene",
            )

        if isinstance(result, dict):
            return result.get("video", result)
        return result

    async def generate_video(
        self,
        image_path: str,
        prompt: str,
    ) -> str:
        """
        Generate a single video from image and prompt with style preservation.

        Style-preservation parameters (conditioning, denoise, guidance) are
        configured at init time via the quality preset or env overrides.

        Args:
            image_path: Path to source image
            prompt: Text prompt with Ovi tokens (<S>...<E>, <AUDCAP>...<ENDAUDCAP>)

        Returns:
            Path to generated video file
        """
        logger.info(
            f"Generating video from: {image_path} "
            f"(steps={self.sample_steps}, conditioning={self.image_conditioning_strength:.2f}, "
            f"denoise={self.denoise_strength:.2f})"
        )
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
                    scene["image_path"],
                    scene["prompt"],
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

    async def __aenter__(self) -> "RunPodManager":
        """Async context manager entry: ensure pod is running."""
        success = await self.ensure_running()
        if not success:
            raise VideoGenerationError("Failed to start Ovi on RunPod pod")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit: shutdown pod."""
        await self.shutdown()


# Backward-compatible alias so existing imports still work:
#   from app.services.ovi_space_manager import OviSpaceManager
OviSpaceManager = RunPodManager


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

    Handles full lifecycle: resume pod -> generate videos -> stop pod.

    Args:
        scenes: List of scene dicts with 'image_path' and 'prompt'
        quality: Video quality (draft/standard/high/ultra)
        auto_shutdown: Stop pod after completion

    Returns:
        List of generated video paths
    """
    async with RunPodManager(quality=quality, auto_shutdown=auto_shutdown) as manager:
        return await manager.generate_videos(scenes)
