"""Shared ComfyUI API client.

Used by both ImageGenerator (Flux + LoRA + PuLID) and LTXVideoGenerator
for common HTTP operations: queuing prompts, polling, uploading/downloading files.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ComfyUIError(Exception):
    """Raised when a ComfyUI API call fails."""
    pass


class ComfyUIClient:
    """Shared HTTP client for ComfyUI API interactions."""

    DEFAULT_POLL_INTERVAL_S = 2.0
    DEFAULT_POLL_TIMEOUT_S = 300.0

    def __init__(
        self,
        base_url: str | None = None,
        poll_interval: float | None = None,
        poll_timeout: float | None = None,
    ):
        self.base_url = (base_url or settings.COMFYUI_URL).rstrip("/")
        self.poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL_S
        self.poll_timeout = poll_timeout or self.DEFAULT_POLL_TIMEOUT_S
        self._http_client: httpx.AsyncClient | None = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy initialization of async HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def check_health(self) -> bool:
        """Check if ComfyUI is reachable."""
        try:
            resp = await self.http_client.get(f"{self.base_url}/system_stats")
            return resp.status_code == 200
        except Exception:
            return False

    async def upload_image(self, local_path: str, filename: str) -> str:
        """Upload an image to ComfyUI's input directory.

        Returns the filename as stored by ComfyUI.
        """
        url = f"{self.base_url}/upload/image"

        with open(local_path, "rb") as f:
            files = {"image": (filename, f, "image/jpeg")}
            data = {"overwrite": "true"}
            response = await self.http_client.post(url, files=files, data=data)

        if response.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI /upload/image returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        result = response.json()
        stored_name = result.get("name", filename)
        logger.info(f"Uploaded image to ComfyUI: {stored_name}")
        return stored_name

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        """POST workflow to ComfyUI /prompt and return the prompt_id."""
        url = f"{self.base_url}/prompt"
        payload = {"prompt": workflow}

        response = await self.http_client.post(url, json=payload)

        if response.status_code != 200:
            detail = response.text[:500]
            raise ComfyUIError(
                f"ComfyUI /prompt returned HTTP {response.status_code}: {detail}"
            )

        data = response.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(
                f"ComfyUI /prompt response missing prompt_id: {data}"
            )

        return prompt_id

    async def poll_for_completion(
        self,
        prompt_id: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Poll GET /history/{prompt_id} until the job finishes or times out.

        Returns the outputs dict from the completed prompt.
        """
        url = f"{self.base_url}/history/{prompt_id}"
        deadline = time.time() + (timeout or self.poll_timeout)

        while time.time() < deadline:
            response = await self.http_client.get(url)
            if response.status_code != 200:
                logger.warning(
                    f"ComfyUI /history returned {response.status_code}, retrying..."
                )
                await asyncio.sleep(self.poll_interval)
                continue

            data = response.json()
            if prompt_id in data:
                history = data[prompt_id]
                # Check for execution error
                status_info = history.get("status", {})
                if status_info.get("status_str") == "error":
                    messages = status_info.get("messages", [])
                    raise ComfyUIError(
                        f"ComfyUI execution error: {messages}"
                    )
                outputs = history.get("outputs")
                if outputs:
                    return outputs

            await asyncio.sleep(self.poll_interval)

        raise ComfyUIError(
            f"ComfyUI prompt {prompt_id} timed out after {timeout or self.poll_timeout}s"
        )

    async def download_file(
        self,
        filename: str,
        subfolder: str = "",
        file_type: str = "output",
    ) -> bytes:
        """Download a file from ComfyUI via GET /view.

        Works for both images and videos.
        """
        url = f"{self.base_url}/view"
        params = {
            "filename": filename,
            "type": file_type,
        }
        if subfolder:
            params["subfolder"] = subfolder

        response = await self.http_client.get(url, params=params)
        if response.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI /view returned HTTP {response.status_code} for {filename}"
            )

        return response.content

    async def check_file_exists(
        self,
        filename: str,
        file_type: str = "input",
    ) -> bool:
        """Check if a file exists in ComfyUI's directory."""
        try:
            resp = await self.http_client.get(
                f"{self.base_url}/view",
                params={"filename": filename, "type": file_type},
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def free_vram(self) -> None:
        """Ask ComfyUI to unload all models and free VRAM."""
        try:
            await self.http_client.post(
                f"{self.base_url}/free",
                json={"unload_models": True, "free_memory": True},
            )
            logger.info("ComfyUI models unloaded from VRAM")
        except Exception as e:
            logger.warning(f"Could not free ComfyUI VRAM: {e}")

    async def get_object_info(self, node_type: str | None = None) -> dict:
        """Query ComfyUI /object_info for available node types.

        If node_type is provided, returns info for that specific node.
        Otherwise returns all available nodes.
        """
        url = f"{self.base_url}/object_info"
        if node_type:
            url = f"{url}/{node_type}"

        response = await self.http_client.get(url)
        if response.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI /object_info returned HTTP {response.status_code}"
            )

        return response.json()
