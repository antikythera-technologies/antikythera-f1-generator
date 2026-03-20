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

# Must match scene clip format exactly for -c copy concat
CLIP_WIDTH = 1920
CLIP_HEIGHT = 1080
CLIP_FPS = 25
CLIP_PIX_FMT = "yuv420p"
CLIP_AUDIO_RATE = 44100

TITLE_DURATION = 4  # seconds
OUTRO_DURATION = 5  # seconds


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

        Scene clips are concatenated with -c copy (zero modification).
        Title and outro are generated as SEPARATE clips prepended/appended.
        Scene audio is NEVER touched.
        """
        logger.info(f"Episode {episode_id}: Starting stitch of {len(clip_paths)} clips")

        episode_dir = self.work_dir / f"episode_{episode_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        all_clips = []

        # Title/outro disabled — pure scene concat only for now
        # TODO: Add title/outro once format compatibility is solved

        # Scene clips — untouched
        all_clips.extend(clip_paths)

        # Outro disabled — pure scene concat only for now

        # Create file list for ffmpeg concat demuxer
        file_list_path = episode_dir / "files.txt"
        with open(file_list_path, "w") as f:
            for clip_path in all_clips:
                escaped_path = clip_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
                logger.debug(f"Added clip: {clip_path}")

        output_path = episode_dir / "final.mp4"

        # Pure stream copy — scene audio untouched
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
            "-c", "copy",
            "-y",
            str(output_path),
        ]

        logger.info(f"Running ffmpeg concat: {len(all_clips)} clips")

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
                logger.error("ffmpeg concat timed out")
                raise VideoStitchError("Video stitching timed out")

            if proc.returncode != 0:
                logger.error(f"ffmpeg concat failed: {stderr.decode()}")
                raise VideoStitchError(f"ffmpeg concat failed: {stderr.decode()}")

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

    async def _generate_title_card(
        self, title: str, subtitle: str, output_path: str
    ) -> None:
        """Generate a title card clip matching scene clip format.

        Black background with centered title text and subtitle.
        Has silent audio track to match scene clip format.
        """
        title_safe = title.upper().replace("'", "'\\\\''").replace(":", "\\:")
        subtitle_safe = subtitle.replace("'", "'\\\\''").replace(":", "\\:")

        font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        font_reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        # Fade in title, then subtitle
        vf = (
            f"drawtext=text='{title_safe}'"
            f":fontfile={font_bold}:fontsize=58:fontcolor=white"
            f":x=(w-text_w)/2:y=(h-text_h)/2-30"
            f":alpha='if(lt(t,0.5),t/0.5,if(gt(t,{TITLE_DURATION-0.5}),({TITLE_DURATION}-t)/0.5,1))'"
            f",drawtext=text='{subtitle_safe}'"
            f":fontfile={font_reg}:fontsize=24:fontcolor=white@0.8"
            f":x=(w-text_w)/2:y=(h-text_h)/2+30"
            f":alpha='if(lt(t,1),t/1,if(gt(t,{TITLE_DURATION-0.5}),({TITLE_DURATION}-t)/0.5,1))'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={CLIP_WIDTH}x{CLIP_HEIGHT}:d={TITLE_DURATION}:r={CLIP_FPS}",
            "-f", "lavfi",
            "-i", f"anullsrc=r={CLIP_AUDIO_RATE}:cl=stereo",
            "-vf", vf,
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", CLIP_PIX_FMT,
            "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-ar", str(CLIP_AUDIO_RATE), "-ac", "2",
            "-t", str(TITLE_DURATION),
            output_path,
        ]

        await self._run_ffmpeg(cmd, "title card")

    async def _generate_outro_card(
        self, next_episode_text: str, output_path: str
    ) -> None:
        """Generate an outro card clip matching scene clip format.

        Black background with branding and next episode teaser.
        Has silent audio track to match scene clip format.
        """
        branding = "ANTIKYTHERA F1"
        branding_safe = branding.replace("'", "'\\\\''")
        next_safe = next_episode_text.replace("'", "'\\\\''").replace(":", "\\:")

        font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        font_reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        vf = (
            f"drawtext=text='{branding_safe}'"
            f":fontfile={font_bold}:fontsize=44:fontcolor=white"
            f":x=(w-text_w)/2:y=(h-text_h)/2-25"
            f":alpha='if(lt(t,1),t/1,1)'"
            f",drawtext=text='{next_safe}'"
            f":fontfile={font_reg}:fontsize=22:fontcolor=white@0.7"
            f":x=(w-text_w)/2:y=(h-text_h)/2+25"
            f":alpha='if(lt(t,1.5),0,if(lt(t,2.5),(t-1.5)/1,1))'"
            f",fade=t=out:st={OUTRO_DURATION-1.5}:d=1.5"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={CLIP_WIDTH}x{CLIP_HEIGHT}:d={OUTRO_DURATION}:r={CLIP_FPS}",
            "-f", "lavfi",
            "-i", f"anullsrc=r={CLIP_AUDIO_RATE}:cl=stereo",
            "-vf", vf,
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", CLIP_PIX_FMT,
            "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-ar", str(CLIP_AUDIO_RATE), "-ac", "2",
            "-t", str(OUTRO_DURATION),
            output_path,
        ]

        await self._run_ffmpeg(cmd, "outro card")

    async def _run_ffmpeg(self, cmd: list, label: str) -> None:
        """Run an ffmpeg command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise VideoStitchError(f"{label} generation timed out")

        if proc.returncode != 0:
            logger.error(f"{label} failed: {stderr.decode()[:300]}")
            raise VideoStitchError(f"{label} generation failed")

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
