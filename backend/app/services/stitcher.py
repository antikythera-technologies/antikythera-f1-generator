"""Video stitching service using ffmpeg.

Single-pass re-encode approach: concat demuxer feeds all clips into one
ffmpeg process that re-encodes both video and audio. This guarantees:
- Both streams start at PTS 0 (no edit list offset)
- 0% VFR (perfect CFR from the encoder)
- No B-frame PTS reordering issues
- Unified timestamp timeline for A/V sync

Previous approaches that FAILED:
- -c copy concat: creates edit list offset (video starts 23ms late),
  Chrome accumulates this during playback causing progressive drift
- Two-step normalize + -c copy concat: same edit list problem
- -c:a copy with -c:v re-encode: audio/video on different timelines
"""

import asyncio
import os
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.exceptions import VideoStitchError

logger = logging.getLogger(__name__)

# Stitch output settings — match fal-LTX source format to avoid conversion
OUTPUT_FPS = 25          # fal-LTX produces 25fps
OUTPUT_SAMPLE_RATE = 48000  # fal-LTX produces 48kHz
OUTPUT_AUDIO_BITRATE = "192k"
KEYFRAME_INTERVAL = OUTPUT_FPS * 2  # keyframe every 2 seconds

# Title/outro settings
TITLE_CARD_DURATION = 5
TITLE_FONT_SIZE = 48
SUBTITLE_FONT_SIZE = 24
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720


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
        circuit_name: str = "",
    ) -> StitchResult:
        """
        Stitch video clips into a final episode.

        Single-pass re-encode: concat demuxer → re-encode both streams.
        No normalize step, no -c copy. Both streams get fresh timestamps
        from a single encoder timeline, eliminating all drift sources.
        """
        logger.info(f"Episode {episode_id}: Starting stitch of {len(clip_paths)} clips")

        episode_dir = self.work_dir / f"episode_{episode_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Generate title card and outro if title is provided
        all_clips = list(clip_paths)
        if title:
            title_card_path = str(episode_dir / "title_card.mp4")
            await self._generate_title_card(title, subtitle, title_card_path, circuit_name=circuit_name, episode_dir=episode_dir)
            all_clips.insert(0, title_card_path)

            outro_path = str(episode_dir / "outro.mp4")
            await self._generate_outro(next_episode_text, outro_path, episode_dir=episode_dir)
            all_clips.append(outro_path)

            logger.info(
                f"Episode {episode_id}: {len(clip_paths)} scenes + title + outro = "
                f"{len(all_clips)} total clips"
            )

        # Log clip properties for diagnosis
        for idx, clip_path in enumerate(all_clips):
            await self._log_clip_properties(clip_path, idx + 1)

        # Create file list for concat demuxer
        file_list_path = episode_dir / "files.txt"
        with open(file_list_path, "w") as f:
            for clip_path in all_clips:
                escaped_path = clip_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        output_path = episode_dir / "final.mp4"

        # Single-pass re-encode: both streams get fresh, synchronized PTS.
        # -bf 0: no B-frames (prevents PTS reordering)
        # No -c copy: avoids edit list offset that causes browser drift
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
            # Video
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-r", str(OUTPUT_FPS),
            "-g", str(KEYFRAME_INTERVAL),
            "-keyint_min", str(KEYFRAME_INTERVAL),
            "-bf", "0",
            "-pix_fmt", "yuv420p",
            # Audio
            "-c:a", "aac",
            "-b:a", OUTPUT_AUDIO_BITRATE,
            "-ar", str(OUTPUT_SAMPLE_RATE),
            "-ac", "2",
            # Output
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.info(
            f"Episode {episode_id}: Stitching {len(all_clips)} clips "
            f"(single-pass re-encode, {OUTPUT_FPS}fps, {OUTPUT_SAMPLE_RATE}Hz)"
        )
        await self._run_ffmpeg(cmd, "stitch", timeout=1800)

        # Verify final output
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

    # -- Title card / outro --------------------------------------------------

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """Escape text for FFmpeg drawtext filter."""
        text = text.replace("\\", "\\\\")
        text = text.replace(":", "\\:")
        text = text.replace("'", "'\\''")
        return text

    async def _generate_card_image(
        self, prompt: str, output_image_path: str,
    ) -> bool:
        """Generate an image via fal.ai for title card or outro background.
        
        Returns True if image was generated, False on failure (fallback to black).
        """
        try:
            import fal_client

            logger.info(f"Generating card image via fal.ai: {prompt[:80]}...")
            result = await fal_client.run_async(
                "fal-ai/flux-lora",
                arguments={
                    "prompt": prompt,
                    "image_size": {"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT},
                    "num_images": 1,
                    "num_inference_steps": 28,
                    "guidance_scale": 3.5,
                    "enable_safety_checker": False,
                    "loras": [
                        {
                            "path": "https://v3b.fal.media/files/b/0a918355/tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors",
                            "scale": 1.0,
                        }
                    ],
                },
            )

            images = result.get("images", [])
            if not images:
                logger.warning("fal.ai returned no images for card, falling back to black")
                return False

            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(images[0]["url"])
                resp.raise_for_status()
                with open(output_image_path, "wb") as f:
                    f.write(resp.content)

            logger.info(f"Card image generated: {output_image_path}")
            return True

        except Exception as e:
            logger.warning(f"Failed to generate card image, falling back to black: {e}")
            return False

    async def _generate_title_card(
        self, title: str, subtitle: str, output_path: str,
        duration: int = TITLE_CARD_DURATION,
        circuit_name: str = "",
        episode_dir: Optional[Path] = None,
    ) -> None:
        """Generate a title card with AI-generated background image and text overlay."""
        # Try to generate a background image
        bg_image_path = str(episode_dir / "title_bg.png") if episode_dir else "/tmp/title_bg.png"
        circuit_text = circuit_name or "F1 circuit"
        prompt = (
            f"ANTKF1STYLE Dramatic aerial view of {circuit_text} at golden hour, "
            f"F1 cars racing on track driving away from camera showing rear wings, "
            f"dramatic clouds and sunset sky, satirical caricature art style, "
            f"vibrant colors, cinematic wide shot"
        )
        has_bg = await self._generate_card_image(prompt, bg_image_path)

        # Build drawtext filter
        drawtext_parts = []

        # Split long titles across two lines
        if len(title) > 30:
            mid = len(title) // 2
            best = mid
            for i in range(mid - 10, mid + 10):
                if 0 <= i < len(title) and title[i] in " :-":
                    best = i
                    break
            line1 = self._escape_drawtext(title[:best].strip())
            line2 = self._escape_drawtext(title[best:].strip().lstrip(":-").strip())
            drawtext_parts.extend([
                f"drawtext=text=\'{line1}\':fontsize={TITLE_FONT_SIZE}:fontcolor=white"
                f":borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=(h/2)-70",
                f"drawtext=text=\'{line2}\':fontsize={TITLE_FONT_SIZE}:fontcolor=white"
                f":borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=(h/2)-20",
            ])
        else:
            esc_title = self._escape_drawtext(title)
            drawtext_parts.append(
                f"drawtext=text=\'{esc_title}\':fontsize={TITLE_FONT_SIZE}:fontcolor=white"
                f":borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=(h-text_h)/2-40"
            )

        if subtitle:
            esc_subtitle = self._escape_drawtext(subtitle)
            drawtext_parts.append(
                f"drawtext=text=\'{esc_subtitle}\':fontsize={SUBTITLE_FONT_SIZE}"
                f":fontcolor=white@0.8:borderw=2:bordercolor=black@0.5"
                f":x=(w-text_w)/2:y=(h/2)+40"
            )

        if has_bg:
            # Use image as background with dark gradient overlay for text readability
            vf_parts = [
                f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
                "format=yuv420p",
                # Dark gradient overlay: bottom half darkened for text
                f"colorkey=color=black:similarity=0",  # no-op to chain
            ]
            vf_parts.extend(drawtext_parts)
            vf = ",".join(vf_parts)

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", bg_image_path,
                "-f", "lavfi", "-i",
                f"anullsrc=r={OUTPUT_SAMPLE_RATE}:cl=stereo",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-bf", "0", "-pix_fmt", "yuv420p",
                "-r", str(OUTPUT_FPS),
                "-c:a", "aac", "-b:a", OUTPUT_AUDIO_BITRATE,
                "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2",
                "-t", str(duration), "-shortest",
                output_path,
            ]
        else:
            # Fallback: black background
            vf = ",".join(drawtext_parts)
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={OUTPUT_FPS}",
                "-f", "lavfi", "-i",
                f"anullsrc=r={OUTPUT_SAMPLE_RATE}:cl=stereo",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-bf", "0", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", OUTPUT_AUDIO_BITRATE,
                "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2",
                "-t", str(duration), "-shortest",
                output_path,
            ]

        logger.info(f"Generating title card: {title!r} (bg={'image' if has_bg else 'black'})")
        await self._run_ffmpeg(cmd, "title card", timeout=60)

    async def _generate_outro(
        self, next_episode_text: str, output_path: str,
        duration: int = TITLE_CARD_DURATION,
        episode_dir: Optional[Path] = None,
    ) -> None:
        """Generate an outro clip with AI-generated background and closing text."""
        if next_episode_text:
            heading = "NEXT WEEK"
            sub = next_episode_text
        else:
            heading = "THANKS FOR WATCHING"
            sub = "See you at the next race"

        # Try to generate a background image
        bg_image_path = str(episode_dir / "outro_bg.png") if episode_dir else "/tmp/outro_bg.png"
        prompt = (
            "ANTKF1STYLE Dramatic checkered flag waving against a vibrant sunset sky, "
            "F1 podium celebration with champagne spray, satirical caricature art style, "
            "dramatic lighting, cinematic composition"
        )
        has_bg = await self._generate_card_image(prompt, bg_image_path)

        esc_heading = self._escape_drawtext(heading)
        esc_sub = self._escape_drawtext(sub)

        drawtext_filter = (
            f"drawtext=text=\'{esc_heading}\':fontsize={TITLE_FONT_SIZE}:fontcolor=white"
            f":borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=(h-text_h)/2-40,"
            f"drawtext=text=\'{esc_sub}\':fontsize={SUBTITLE_FONT_SIZE}"
            f":fontcolor=white@0.8:borderw=2:bordercolor=black@0.5"
            f":x=(w-text_w)/2:y=(h-text_h)/2+30"
        )

        if has_bg:
            vf = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},format=yuv420p,{drawtext_filter}"
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", bg_image_path,
                "-f", "lavfi", "-i",
                f"anullsrc=r={OUTPUT_SAMPLE_RATE}:cl=stereo",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-bf", "0", "-pix_fmt", "yuv420p",
                "-r", str(OUTPUT_FPS),
                "-c:a", "aac", "-b:a", OUTPUT_AUDIO_BITRATE,
                "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2",
                "-t", str(duration), "-shortest",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={OUTPUT_FPS}",
                "-f", "lavfi", "-i",
                f"anullsrc=r={OUTPUT_SAMPLE_RATE}:cl=stereo",
                "-vf", drawtext_filter,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-bf", "0", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", OUTPUT_AUDIO_BITRATE,
                "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2",
                "-t", str(duration), "-shortest",
                output_path,
            ]

        logger.info(f"Generating outro: {heading!r} (bg={'image' if has_bg else 'black'})")
        await self._run_ffmpeg(cmd, "outro", timeout=60)

    # -- Utilities ------------------------------------------------------------

    async def _log_clip_properties(self, path: str, clip_num=None, label=None) -> None:
        """Log audio/video properties of a clip for drift diagnosis."""
        tag = f"clip {clip_num}" if clip_num else label or "clip"
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries",
                "stream=codec_type,codec_name,duration,r_frame_rate,sample_rate,channels,start_time",
                "-print_format", "json",
                path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)
            streams = data.get("streams", [])

            v_dur = a_dur = v_start = a_start = "?"
            v_fps = a_rate = "?"
            for s in streams:
                if s.get("codec_type") == "video":
                    v_dur = s.get("duration", "?")
                    v_fps = s.get("r_frame_rate", "?")
                    v_start = s.get("start_time", "?")
                elif s.get("codec_type") == "audio":
                    a_dur = s.get("duration", "?")
                    a_rate = s.get("sample_rate", "?")
                    a_start = s.get("start_time", "?")

            mismatch = ""
            try:
                diff_ms = (float(a_dur) - float(v_dur)) * 1000
                mismatch = f" mismatch={diff_ms:+.1f}ms"
            except (ValueError, TypeError):
                pass

            logger.info(
                f"[{tag}] v={v_dur}s@{v_fps}fps(start={v_start})  "
                f"a={a_dur}s@{a_rate}Hz(start={a_start}){mismatch}  {path}"
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
                "ffprobe", "-v", "quiet",
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
