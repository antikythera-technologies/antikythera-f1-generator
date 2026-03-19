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
        self.codec = settings.VIDEO_CODEC
        self.audio_codec = settings.VIDEO_AUDIO_CODEC
        self.crf = settings.VIDEO_CRF

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

        Args:
            episode_id: Episode ID for organizing temp files
            clip_paths: Ordered list of paths to video clips

        Returns:
            StitchResult with output path and metadata
        """
        logger.info(f"Episode {episode_id}: Starting stitch of {len(clip_paths)} clips")

        # Create episode work directory
        episode_dir = self.work_dir / f"episode_{episode_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Apply title overlay to first clip (intro/title card)
        if title and len(clip_paths) > 0:
            intro_output = str(episode_dir / "clip_01_titled.mp4")
            clip_paths[0] = await self._apply_title_overlay(
                clip_paths[0], title, subtitle, intro_output
            )

        # Apply outro overlay to last clip
        if next_episode_text and len(clip_paths) > 1:
            outro_output = str(episode_dir / f"clip_{len(clip_paths):02d}_outro.mp4")
            clip_paths[-1] = await self._apply_outro_overlay(
                clip_paths[-1], next_episode_text, outro_output
            )

        # Create file list for ffmpeg concat
        file_list_path = episode_dir / "files.txt"
        with open(file_list_path, "w") as f:
            for clip_path in clip_paths:
                escaped_path = clip_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
                logger.debug(f"Added clip: {clip_path}")

        # Output path
        output_path = episode_dir / "final.mp4"

        # Build ffmpeg command — use -preset fast for acceptable speed on VPS
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
            "-c:v", self.codec,
            "-c:a", "copy",
            "-preset", "fast",
            "-crf", str(self.crf),
            "-y",
            str(output_path),
        ]

        logger.info(f"Running ffmpeg: {' '.join(cmd)}")

        try:
            # Use async subprocess to avoid blocking the event loop
            # (sync subprocess.run kills DB connections during long encodes)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=900
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.error("ffmpeg timed out after 15 minutes")
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
            return settings.VIDEO_TOTAL_DURATION_SECONDS

    async def _apply_title_overlay(
        self,
        clip_path: str,
        title: str,
        subtitle: str,
        output_path: str,
    ) -> str:
        """Overlay episode title text on the intro clip using ffmpeg drawtext."""
        title_safe = title.upper().replace("'", "'\\\\''").replace(":", "\\:")
        subtitle_safe = subtitle.replace("'", "'\\\\''").replace(":", "\\:")

        font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        font_sub = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        filter_complex = (
            f"drawtext=text='{title_safe}'"
            f":fontfile={font}:fontsize=56:fontcolor=white"
            f":borderw=4:bordercolor=black@0.7"
            f":shadowcolor=black@0.5:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y=(h-text_h)/2-35"
            f":alpha='if(lt(t,0.5),t/0.5,if(lt(t,4),1,(5-t)/1))'"
            f",drawtext=text='{subtitle_safe}'"
            f":fontfile={font_sub}:fontsize=24:fontcolor=white@0.85"
            f":borderw=2:bordercolor=black@0.5"
            f":x=(w-text_w)/2:y=(h-text_h)/2+35"
            f":alpha='if(lt(t,0.8),t/0.8,if(lt(t,4),1,(5-t)/1))'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-vf", filter_complex,
            "-c:v", self.codec, "-crf", str(self.crf), "-preset", "fast",
            "-c:a", "copy",
            output_path,
        ]

        logger.info(f"Applying title overlay: {title}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.warning(f"Title overlay failed: {stderr.decode()[:200]}")
            return clip_path
        return output_path

    async def _apply_outro_overlay(
        self,
        clip_path: str,
        next_episode_text: str,
        output_path: str,
    ) -> str:
        """Overlay outro text and fade-to-black on the final clip."""
        branding = "ANTIKYTHERA F1"
        branding_safe = branding.replace("'", "'\\\\''")
        next_safe = next_episode_text.replace("'", "'\\\\''").replace(":", "\\:")

        filter_complex = (
            f"drawtext=text='{branding_safe}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            f":fontsize=40:fontcolor=white"
            f":borderw=3:bordercolor=black@0.7"
            f":shadowcolor=black@0.5:shadowx=2:shadowy=2"
            f":x=(w-text_w)/2:y=(h-text_h)/2-25"
            f":alpha='if(lt(t,1),t/1,1)'"
            f",drawtext=text='{next_safe}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            f":fontsize=22:fontcolor=white@0.8"
            f":borderw=1:bordercolor=black@0.5"
            f":x=(w-text_w)/2:y=(h-text_h)/2+25"
            f":alpha='if(lt(t,1.5),0,if(lt(t,2.5),(t-1.5)/1,1))'"
            f",fade=t=out:st=6:d=2"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-vf", filter_complex,
            "-c:v", self.codec, "-crf", str(self.crf), "-preset", "fast",
            "-c:a", "copy",
            output_path,
        ]

        logger.info(f"Applying outro overlay")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.warning(f"Outro overlay failed: {stderr.decode()[:200]}")
            return clip_path
        return output_path

    async def cleanup(self, episode_id: int) -> None:
        """Clean up temporary files for an episode."""
        episode_dir = self.work_dir / f"episode_{episode_id}"

        if episode_dir.exists():
            import shutil
            shutil.rmtree(episode_dir)
            logger.info(f"Cleaned up temp files for episode {episode_id}")
