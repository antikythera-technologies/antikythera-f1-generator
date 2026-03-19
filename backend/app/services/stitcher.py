"""Video stitching service using ffmpeg."""

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from app.config import settings
from app.exceptions import VideoStitchError

logger = logging.getLogger(__name__)


@dataclass
class StitchResult:
    """Result of video stitching operation."""
    output_path: str
    duration_seconds: int
    file_size_bytes: int


class VideoStitcher:
    """Service for stitching video clips together using ffmpeg."""

    def __init__(self, work_dir: str = "/tmp/videos"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    async def stitch(
        self,
        episode_id: int,
        clip_paths: List[str],
        title: str = "",
        subtitle: str = "",
        next_episode_text: str = "",
    ) -> StitchResult:
        """
        Stitch multiple video clips into a single video.

        Pure stream copy — no re-encoding of video or audio.
        Scene clips are concatenated exactly as-is.
        """
        logger.info(f"Episode {episode_id}: Starting stitch of {len(clip_paths)} clips")

        episode_dir = self.work_dir / f"episode_{episode_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Create file list for ffmpeg concat demuxer
        file_list_path = episode_dir / "files.txt"
        with open(file_list_path, "w") as f:
            for clip_path in clip_paths:
                escaped_path = clip_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
                logger.debug(f"Added clip: {clip_path}")

        output_path = episode_dir / "final.mp4"

        # Pure stream copy — zero re-encoding, zero audio modification
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
            "-c", "copy",
            "-y",
            str(output_path),
        ]

        logger.info(f"Running ffmpeg: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=300
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.error("ffmpeg timed out")
                raise VideoStitchError("Video stitching timed out")

            if proc.returncode != 0:
                logger.error(f"ffmpeg failed: {stderr.decode()}")
                raise VideoStitchError(f"ffmpeg failed: {stderr.decode()}")

            logger.info(f"Stitch complete: {output_path}")

            file_size = output_path.stat().st_size
            duration = self._get_duration(str(output_path))

            return StitchResult(
                output_path=str(output_path),
                duration_seconds=duration,
                file_size_bytes=file_size,
            )

        except FileNotFoundError:
            logger.error("ffmpeg not found in PATH")
            raise VideoStitchError("ffmpeg not installed or not in PATH")

    def _get_duration(self, video_path: str) -> int:
        """Get video duration in seconds using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return int(float(result.stdout.strip()))
        except Exception as e:
            logger.warning(f"Could not get video duration: {e}")
            return 0

    async def cleanup(self, episode_id: int) -> None:
        """Clean up temporary files for an episode."""
        episode_dir = self.work_dir / f"episode_{episode_id}"
        if episode_dir.exists():
            import shutil
            shutil.rmtree(episode_dir)
            logger.info(f"Cleaned up temp files for episode {episode_id}")
