"""Audio mixer: mux TTS speech onto silent video clips.

Takes a silent video (from LTX) and a TTS audio file, synchronizes
their durations, and produces a final video with embedded audio.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MixResult:
    """Result of audio mixing / muxing operation."""

    output_path: str
    video_duration: float
    audio_duration: float
    tempo_factor: float  # 1.0 = normal, >1.0 = sped up to fit
    generation_time_ms: int


# Maximum tempo speedup before it sounds unnatural
MAX_TEMPO = 1.25
# Minimum tempo (slowdown) before it sounds draggy
MIN_TEMPO = 0.70
# Target fill: speech should cover this fraction of the video duration
FILL_TARGET = 0.90


class AudioMixer:
    """Mix TTS audio onto video clips using ffmpeg.

    Handles:
    - Duration matching (pad short audio with silence, speed up long audio)
    - Muxing audio onto silent video
    - Adding silent audio tracks to dialogue-free scenes
    """

    def __init__(self, output_dir: str = "/tmp/f1-mixed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def mux_audio_onto_video(
        self,
        video_path: str,
        audio_path: Optional[str],
        scene_number: int = 0,
        episode_id: int = 0,
    ) -> MixResult:
        """Mux audio onto a video clip, handling duration mismatches.

        If audio is shorter than video: audio is padded with silence.
        If audio is longer than video: audio is sped up (up to 1.25x),
            or truncated if still too long.
        If audio_path is None: a silent audio track is added.

        Args:
            video_path: Path to input video (silent).
            audio_path: Path to audio file, or None for silence.
            scene_number: Scene number for file naming.
            episode_id: Episode ID for file naming.

        Returns:
            MixResult with path to the output video with audio.
        """
        start_time = time.time()

        video_duration = await self._get_duration(video_path)
        output_path = (
            self.output_dir
            / f"ep{episode_id}_scene_{scene_number:02d}_mixed.mp4"
        )

        if audio_path is None:
            # No dialogue — add silent audio track
            await self._add_silent_audio(video_path, str(output_path), video_duration)
            elapsed_ms = int((time.time() - start_time) * 1000)

            return MixResult(
                output_path=str(output_path),
                video_duration=video_duration,
                audio_duration=video_duration,
                tempo_factor=1.0,
                generation_time_ms=elapsed_ms,
            )

        audio_duration = await self._get_duration(audio_path)
        tempo_factor = 1.0

        if audio_duration <= 0:
            raise RuntimeError(
                f"Scene {scene_number}: Audio file has zero duration — "
                f"TTS likely failed. Path: {audio_path}"
            )

        # Target: speech should fill ~90% of video, leaving a small
        # natural pause at the end. We slow down or speed up accordingly.
        target_duration = video_duration * FILL_TARGET

        if audio_duration > video_duration:
            # Audio is longer than video — speed it up
            tempo_factor = audio_duration / video_duration

            if tempo_factor > MAX_TEMPO:
                logger.warning(
                    f"Scene {scene_number}: Audio {audio_duration:.2f}s > video "
                    f"{video_duration:.2f}s, tempo {tempo_factor:.2f}x exceeds "
                    f"max {MAX_TEMPO}x — will truncate at video end"
                )
                tempo_factor = MAX_TEMPO

            logger.info(
                f"Scene {scene_number}: Speeding up audio {tempo_factor:.2f}x "
                f"({audio_duration:.2f}s → {video_duration:.2f}s)"
            )

        elif audio_duration < target_duration:
            # Audio is too short — slow it down to fill the scene
            tempo_factor = audio_duration / target_duration

            if tempo_factor < MIN_TEMPO:
                logger.info(
                    f"Scene {scene_number}: Audio {audio_duration:.2f}s very short, "
                    f"capping slowdown at {MIN_TEMPO}x (would need {tempo_factor:.2f}x)"
                )
                tempo_factor = MIN_TEMPO
            else:
                logger.info(
                    f"Scene {scene_number}: Slowing audio {tempo_factor:.2f}x "
                    f"({audio_duration:.2f}s → {target_duration:.2f}s)"
                )

        if abs(tempo_factor - 1.0) > 0.01:
            await self._mux_with_tempo(
                video_path, audio_path, str(output_path),
                video_duration, tempo_factor,
            )
        else:
            await self._mux_with_pad(
                video_path, audio_path, str(output_path), video_duration,
            )

        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Scene {scene_number}: Audio mixed in {elapsed_ms}ms "
            f"(tempo={tempo_factor:.2f}x)"
        )

        return MixResult(
            output_path=str(output_path),
            video_duration=video_duration,
            audio_duration=audio_duration,
            tempo_factor=tempo_factor,
            generation_time_ms=elapsed_ms,
        )

    async def _mux_with_pad(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        video_duration: float,
    ) -> None:
        """Mux audio onto video, padding short audio with silence."""
        # apad pads with silence to match video duration.
        # Force stereo (-ac 2) since Edge TTS outputs mono 24kHz.
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            f"[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={video_duration}[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            "-t", str(video_duration),
            output_path,
        ]
        await self._run_ffmpeg(cmd)

    async def _mux_with_tempo(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        video_duration: float,
        tempo: float,
    ) -> None:
        """Mux audio onto video with tempo adjustment."""
        # atempo filter adjusts speed. Range 0.5-100.0 per instance.
        tempo_filter = self._build_tempo_filter(tempo)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            f"[1:a]{tempo_filter},aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={video_duration}[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            "-t", str(video_duration),
            output_path,
        ]
        await self._run_ffmpeg(cmd)

    async def _add_silent_audio(
        self,
        video_path: str,
        output_path: str,
        duration: float,
    ) -> None:
        """Add a silent stereo audio track to a video."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            "-t", str(duration),
            output_path,
        ]
        await self._run_ffmpeg(cmd)

    @staticmethod
    def _build_tempo_filter(tempo: float) -> str:
        """Build atempo filter chain for arbitrary tempo values.

        atempo accepts 0.5-100.0, so for most cases a single filter works.
        """
        if 0.5 <= tempo <= 100.0:
            return f"atempo={tempo:.4f}"

        # Chain multiple atempo filters for extreme values
        filters = []
        remaining = tempo
        while remaining > 100.0:
            filters.append("atempo=100.0")
            remaining /= 100.0
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        filters.append(f"atempo={remaining:.4f}")
        return ",".join(filters)

    @staticmethod
    async def _get_duration(file_path: str) -> float:
        """Get media duration in seconds using ffprobe."""
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        try:
            duration = float(stdout.decode().strip())
        except (ValueError, AttributeError):
            raise RuntimeError(
                f"Cannot determine duration of {file_path} — "
                f"ffprobe returned: {stdout.decode().strip()!r}. "
                f"File may be corrupt or missing."
            )

        if duration <= 0:
            raise RuntimeError(
                f"Media has zero/negative duration ({duration}s): {file_path}"
            )

        return duration

    @staticmethod
    async def _run_ffmpeg(cmd: list[str]) -> None:
        """Run an ffmpeg command and raise on failure."""
        logger.debug(f"Running: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode()[-500:]  # Last 500 chars of error
            raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {error_msg}")
