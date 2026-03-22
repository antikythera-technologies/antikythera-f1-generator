"""Video stitching service using ffmpeg."""

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from app.exceptions import VideoStitchError

logger = logging.getLogger(__name__)

# Target format for normalized clips
TARGET_FPS = 24
TARGET_SAMPLE_RATE = 44100
TARGET_AUDIO_BITRATE = "192k"
# Keyframe every 2 seconds at 24fps
KEYFRAME_INTERVAL = TARGET_FPS * 2  # 48


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

        Two-step process to eliminate audio drift:
        1. Normalize each clip: re-encode to identical format with matching
           audio/video durations.
        2. Concatenate normalized clips via concat demuxer with stream copy.

        Scene clips in MinIO are NEVER modified — only temp copies are used.
        """
        logger.info(f"Episode {episode_id}: Starting stitch of {len(clip_paths)} clips")

        episode_dir = self.work_dir / f"episode_{episode_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Diagnose + normalize each clip to identical format.
        # This eliminates per-clip A/V duration mismatch, VFR, different
        # sample rates, missing audio — any property that causes drift.
        normalized_paths = []
        for idx, clip_path in enumerate(clip_paths):
            # Log clip properties for diagnosis
            await self._log_clip_properties(clip_path, idx + 1)

            norm_path = str(episode_dir / f"norm_{idx:02d}.mp4")
            await self._normalize_clip(clip_path, norm_path, idx + 1, len(clip_paths))
            normalized_paths.append(norm_path)

        logger.info(f"Episode {episode_id}: Normalized {len(normalized_paths)} clips")

        # Step 2: Concatenate normalized clips.
        # All clips now have identical format — safe to stream-copy.
        file_list_path = episode_dir / "files.txt"
        with open(file_list_path, "w") as f:
            for norm_path in normalized_paths:
                escaped_path = norm_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        output_path = episode_dir / "final.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.info(f"Episode {episode_id}: Concatenating {len(normalized_paths)} normalized clips")
        await self._run_ffmpeg(cmd, "concat", timeout=600)

        # Verify final output A/V sync
        await self._log_clip_properties(str(output_path), label="FINAL")

        file_size = output_path.stat().st_size
        duration = self._get_duration(str(output_path))

        logger.info(
            f"Episode {episode_id}: Stitch complete — "
            f"{duration}s, {file_size / (1024*1024):.1f}MB"
        )

        return StitchResult(
            output_path=str(output_path),
            duration_seconds=duration,
            file_size_bytes=file_size,
        )

    async def _normalize_clip(
        self, input_path: str, output_path: str, clip_num: int, total: int
    ) -> None:
        """
        Re-encode a clip to a canonical format with matching A/V duration.

        - Video: H.264, CFR 24fps, yuv420p, CRF 18, keyframes every 2s
        - Audio: AAC 192k, 44100 Hz, stereo, resampled to match video timing
        - aresample=async=1: actively corrects audio timing to match video
        - -shortest: trims to the shorter stream
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            # Video: constant frame rate with keyframes
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-r", str(TARGET_FPS),
            "-g", str(KEYFRAME_INTERVAL),
            "-keyint_min", str(KEYFRAME_INTERVAL),
            "-pix_fmt", "yuv420p",
            # Audio: standardized format with active sync correction
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "aac",
            "-b:a", TARGET_AUDIO_BITRATE,
            "-ar", str(TARGET_SAMPLE_RATE),
            "-ac", "2",
            # Trim to shorter stream
            "-shortest",
            output_path,
        ]

        logger.debug(f"Normalizing clip {clip_num}/{total}: {input_path}")
        await self._run_ffmpeg(cmd, f"normalize clip {clip_num}/{total}", timeout=300)

    async def _log_clip_properties(self, path: str, clip_num=None, label=None) -> None:
        """Log audio/video properties of a clip for drift diagnosis."""
        tag = f"clip {clip_num}" if clip_num else label or "clip"
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries",
                "stream=codec_type,codec_name,duration,r_frame_rate,sample_rate,channels",
                "-print_format", "json",
                path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)
            streams = data.get("streams", [])

            v_dur = a_dur = "N/A"
            v_fps = a_rate = "N/A"
            for s in streams:
                if s.get("codec_type") == "video":
                    v_dur = s.get("duration", "N/A")
                    v_fps = s.get("r_frame_rate", "N/A")
                elif s.get("codec_type") == "audio":
                    a_dur = s.get("duration", "N/A")
                    a_rate = s.get("sample_rate", "N/A")

            # Calculate mismatch
            mismatch = ""
            try:
                diff_ms = (float(a_dur) - float(v_dur)) * 1000
                mismatch = f" mismatch={diff_ms:+.1f}ms"
            except (ValueError, TypeError):
                pass

            logger.info(
                f"[{tag}] video={v_dur}s@{v_fps}fps  audio={a_dur}s@{a_rate}Hz{mismatch}  {path}"
            )
        except Exception as e:
            logger.warning(f"[{tag}] Could not probe: {e}")

    async def _run_ffmpeg(self, cmd: list, label: str, timeout: int = 300) -> None:
        """Run an ffmpeg command asynchronously."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("ffmpeg not found in PATH")
            raise VideoStitchError("ffmpeg not installed or not in PATH")

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.error(f"{label} timed out after {timeout}s")
            raise VideoStitchError(f"{label} timed out")

        if proc.returncode != 0:
            error_msg = stderr.decode()[:500]
            logger.error(f"{label} failed: {error_msg}")
            raise VideoStitchError(f"{label} failed: {error_msg}")

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
