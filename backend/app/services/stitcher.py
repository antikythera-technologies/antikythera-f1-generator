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
        Stitch video clips into a final episode.

        Uses MPEG-TS intermediate format to avoid audio drift.
        Each clip is repackaged to .ts (lossless), concatenated via
        the concat protocol (which handles timestamps properly),
        then remuxed to .mp4. Audio/video data is never re-encoded.
        """
        logger.info(f"Episode {episode_id}: Starting stitch of {len(clip_paths)} clips")

        episode_dir = self.work_dir / f"episode_{episode_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Convert each clip to MPEG-TS (lossless repackage)
        ts_paths = []
        for idx, clip_path in enumerate(clip_paths):
            ts_path = str(episode_dir / f"clip_{idx:02d}.ts")
            cmd = [
                "ffmpeg", "-y",
                "-i", clip_path,
                "-c", "copy",
                "-bsf:v", "h264_mp4toannexb",
                "-f", "mpegts",
                ts_path,
            ]
            await self._run_ffmpeg(cmd, f"ts convert clip {idx+1}")
            ts_paths.append(ts_path)

        logger.info(f"Converted {len(ts_paths)} clips to MPEG-TS")

        # Step 2: Concat via TS protocol + remux to MP4
        output_path = episode_dir / "final.mp4"
        concat_input = "concat:" + "|".join(ts_paths)

        cmd = [
            "ffmpeg", "-y",
            "-i", concat_input,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            str(output_path),
        ]

        logger.info(f"Concatenating {len(ts_paths)} TS clips to MP4")

        await self._run_ffmpeg(cmd, "concat to mp4")

        logger.info(f"Stitch complete: {output_path}")

        file_size = output_path.stat().st_size
        duration = self._get_duration(str(output_path))

        return StitchResult(
            output_path=str(output_path),
            duration_seconds=duration,
            file_size_bytes=file_size,
        )

    async def _run_ffmpeg(self, cmd: list, label: str) -> None:
        """Run an ffmpeg command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise VideoStitchError(f"{label} timed out")

        if proc.returncode != 0:
            logger.error(f"{label} failed: {stderr.decode()[:300]}")
            raise VideoStitchError(f"{label} failed")

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
