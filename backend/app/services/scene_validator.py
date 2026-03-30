"""Scene quality validator using Claude Vision API."""

import base64
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Video backends where photorealistic drift is expected (LoRA style fades in motion)
DRIFT_BACKENDS = {"fal-ltx", "fal-ovi", "fal-kling-std", "fal-kling-pro", "fal-kling-o1-flf", "fal-vidu-q1-flf", "fal-wan-flf"}


@dataclass
class CheckResult:
    """Result of a single quality check."""
    name: str
    passed: bool
    confidence: float
    issue: Optional[str] = None


@dataclass
class SceneValidation:
    """Validation result for a single scene."""
    scene_number: int
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "scene_number": self.scene_number,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "confidence": c.confidence, "issue": c.issue}
                for c in self.checks
            ],
            "issues": self.issues,
        })


@dataclass
class ImageValidation:
    """Validation result for a single start frame image."""
    scene_number: int
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class AudioValidation:
    """Result of audio validation checks."""
    passed: bool = True
    has_audio_track: bool = False
    is_silent: bool = False           # True = bad
    has_clipping: bool = False        # True = bad
    speech_detected: bool = False     # False when expected = bad
    duration_match: bool = True
    per_second_rms: list = field(default_factory=list)
    issues: list = field(default_factory=list)


@dataclass
class EpisodeValidation:
    """Validation result for a full episode."""
    episode_id: int
    total_scenes: int
    passed_scenes: int
    failed_scenes: int
    scene_results: list[SceneValidation] = field(default_factory=list)


class SceneValidator:
    """Validates scene quality using ffmpeg frame extraction + Claude Vision."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-20250514"

    async def validate_episode(self, scenes: list) -> EpisodeValidation:
        """Validate all scenes in an episode."""
        results = []
        for scene in scenes:
            try:
                result = await self.validate_scene(scene)
                results.append(result)
            except Exception as e:
                logger.error(f"Scene {scene.scene_number} validation failed: {e}")
                results.append(SceneValidation(
                    scene_number=scene.scene_number,
                    passed=False,
                    issues=[f"Validation error: {str(e)}"],
                ))

        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        return EpisodeValidation(
            episode_id=scenes[0].episode_id if scenes else 0,
            total_scenes=len(results),
            passed_scenes=passed,
            failed_scenes=failed,
            scene_results=results,
        )

    async def validate_scene(self, scene) -> SceneValidation:
        """Validate a single scene by extracting frames and evaluating with Claude Vision."""
        if not scene.video_clip_path:
            return SceneValidation(
                scene_number=scene.scene_number,
                passed=False,
                issues=["No video clip path"],
            )

        from app.services.storage import StorageService
        storage = StorageService()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, f"scene_{scene.scene_number:02d}.mp4")
            bucket, object_name = scene.video_clip_path.split("/", 1)
            await storage.download_file(bucket, object_name, video_path)

            frames = await self._extract_frames(video_path, tmpdir)
            if not frames:
                return SceneValidation(
                    scene_number=scene.scene_number,
                    passed=False,
                    issues=["Failed to extract frames from video"],
                )

            skip_style = (scene.video_generator or "") in DRIFT_BACKENDS

            return await self._evaluate_frames(frames, scene, skip_style=skip_style)

    async def _extract_frames(self, video_path: str, output_dir: str) -> list[str]:
        """Extract 5 frames spread across the video clip."""
        frame_paths = []

        probe_cmd = [
            "ffprobe", "-v", "quiet",
            "-count_frames",
            "-show_entries", "stream=nb_read_frames",
            "-of", "default=nokey=1:noprint_wrappers=1",
            video_path,
        ]
        try:
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            total_frames = int(result.stdout.strip().split("\n")[0])
        except Exception:
            total_frames = 150

        sample_points = [0, 0.25, 0.5, 0.75, 0.95]
        frame_numbers = [min(int(p * total_frames), max(total_frames - 1, 0)) for p in sample_points]
        frame_numbers = sorted(set(frame_numbers))

        for i, frame_num in enumerate(frame_numbers):
            output_path = os.path.join(output_dir, f"frame_{i:02d}.png")
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vf", f"select=eq(n\\,{frame_num})",
                "-vframes", "1",
                "-vsync", "vfr",
                output_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    frame_paths.append(output_path)
            except Exception as e:
                logger.warning(f"Frame extraction failed for frame {frame_num}: {e}")

        return frame_paths

    async def _evaluate_frames(
        self, frame_paths: list[str], scene, skip_style: bool = False
    ) -> SceneValidation:
        """Send frames to Claude Vision for quality evaluation."""
        image_content = []
        for path in frame_paths:
            with open(path, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode("utf-8")
            image_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": data,
                },
            })

        video_gen = scene.video_generator or "unknown"
        scene_context = f"""Scene {scene.scene_number}:
- Action: {scene.action_description or 'N/A'}
- Dialogue: {scene.dialogue or 'N/A'}
- Scene type: {scene.scene_type or 'N/A'}
- Video generator: {video_gen}"""

        if skip_style:
            style_instruction = """- STYLE: SKIP this check — set passed=true. This scene uses a video model that naturally
  drifts from caricature to photorealistic during motion. This is expected, not a defect."""
        else:
            style_instruction = """- STYLE: Should be caricature/cartoon style (pass) vs photorealistic (fail).
  Missing LoRA = photorealistic = fail."""

        prompt = f"""You are a quality checker for AI-generated satirical F1 racing videos.
These {len(frame_paths)} frames are sampled across a single 5-second scene (evenly spread from start to end).

{scene_context}

Evaluate these frames on 6 criteria. Return ONLY valid JSON (no markdown):

{{
  "style": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "character": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "artifacts": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "composition": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "text": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "direction": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }}
}}

Check definitions:
{style_instruction}
- CHARACTER: If a person is shown, do they look consistent across frames? Major morphing = fail. No person = pass.
- ARTIFACTS: Check for wipe lines, ghosting, glitches, static noise, color banding. Minor = pass, major = fail.
- COMPOSITION: Is the main subject fully visible and not badly cropped? Extreme zoom cutting off heads = fail.
- TEXT: Check ALL frames carefully for any visible text, words, letters, numbers, watermarks, captions,
  or writing that was NOT intentionally part of the scene (e.g. on scoreboards or TV graphics).
  AI models sometimes hallucinate random text, logos, or gibberish writing onto surfaces, signs, or clothing.
  Any visible text that looks AI-generated, garbled, or out of place = FAIL.
  Legitimate in-world text (like real sponsor logos on F1 cars, if clearly rendered) = pass.
  When in doubt, fail — false positives are better than missing embedded text.
- DIRECTION: If the scene shows racing cars or vehicles on a track, check that ALL cars face and
  move in the SAME direction. Cars driving against the flow of the race (facing opposite to others) = FAIL.
  If no vehicles are shown, or only one car is visible, = pass.
  This is critical for racing scenes — backwards-facing cars break immersion completely."""

        content = image_content + [{"type": "text", "text": prompt}]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=768,
                messages=[{"role": "user", "content": content}],
            )

            response_text = response.content[0].text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("\n", 1)[1]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()

            result = json.loads(response_text)

            checks = []
            issues = []
            all_passed = True

            for check_name in ["style", "character", "artifacts", "composition", "text", "direction"]:
                check_data = result.get(check_name, {})
                passed = check_data.get("passed", True)
                confidence = check_data.get("confidence", 0.5)
                issue = check_data.get("issue")

                checks.append(CheckResult(
                    name=check_name,
                    passed=passed,
                    confidence=confidence,
                    issue=issue,
                ))

                if not passed:
                    all_passed = False
                    if issue:
                        issues.append(f"{check_name}: {issue}")

            return SceneValidation(
                scene_number=scene.scene_number,
                passed=all_passed,
                checks=checks,
                issues=issues,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Vision response: {e}")
            return SceneValidation(
                scene_number=scene.scene_number,
                passed=False,
                issues=[f"Vision API response parse error: {str(e)}"],
            )
        except Exception as e:
            logger.error(f"Vision API call failed: {e}")
            return SceneValidation(
                scene_number=scene.scene_number,
                passed=False,
                issues=[f"Vision API error: {str(e)}"],
            )

    async def validate_image(
        self,
        image_path: str,
        scene_number: int,
        scene_type: str = None,
        face_visible: bool = True,
        reference_image_path: str = None,
        prompt_text: str = None,
        team_context: dict = None,
    ) -> ImageValidation:
        """Validate a start frame image BEFORE generating expensive video.

        Checks: text, style, composition, direction, physical_accuracy,
        team_colours, f1_accuracy, character_match.
        Cost: ~$0.003 per call.
        """
        # Encode image
        with open(image_path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        image_content = [{
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data},
        }]

        # Optionally encode reference image for comparison
        if reference_image_path and os.path.exists(reference_image_path):
            with open(reference_image_path, "rb") as f:
                ref_data = base64.standard_b64encode(f.read()).decode("utf-8")
            image_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": ref_data},
            })
            ref_note = "The SECOND image is the character reference photo. Check if the face in the first image matches."
        else:
            ref_note = ""

        face_note = "A character face should be clearly visible." if face_visible else "No character face should be visible (wide/action shot)."

        # Build prompt context section
        prompt_context = ""
        if prompt_text:
            prompt_context += f"\nThe original generation prompt was: '{prompt_text}'. Compare whether the image matches what was requested."

        team_note = ""
        if team_context:
            tn = team_context.get("team_name", "")
            cd = team_context.get("car_description", "")
            pc = team_context.get("primary_colour", "")
            sc = team_context.get("secondary_colour", "")
            parts = []
            if tn:
                parts.append(f"Expected team: {tn}")
            if cd:
                parts.append(f"Car: {cd}")
            if pc or sc:
                colours = ", ".join(filter(None, [pc, sc]))
                parts.append(f"Team colours: {colours}")
            if parts:
                team_note = "\n" + ". ".join(parts) + "."

        prompt = f"""You are a quality checker for AI-generated satirical F1 racing images.
This is a start frame for scene {scene_number} (type: {scene_type or 'unknown'}).
{face_note}
{ref_note}{prompt_context}{team_note}

Evaluate this image CAREFULLY. Return ONLY valid JSON (no markdown):

{{
  "text": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "style": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "composition": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "direction": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "physical_accuracy": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "team_colours": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "f1_accuracy": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "character_match": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }}
}}

Checks:
- TEXT: Any visible text, words, letters, numbers, watermarks, garbled writing = FAIL.
  Real F1 sponsor logos (clearly rendered) = pass. AI-generated gibberish text = FAIL.
- STYLE: Must be satirical caricature style with oversized heads, dramatic expressions.
  Photorealistic or generic 3D render = FAIL. Cartoon/caricature = PASS.
- COMPOSITION: Main subject must be fully visible. Head, hair, shoulders clearly in frame
  with space above head. Head cropped or extreme zoom = FAIL.
  For action scenes: cars should be clearly visible, properly composed.
- DIRECTION: If racing cars or vehicles are visible, ALL cars MUST face and point in the
  SAME direction. Any car facing the opposite way to others = FAIL. This is critical.
  If the prompt says cockpit/onboard POV, cars ahead should face AWAY from the viewer.
  If no vehicles are shown = PASS.
- PHYSICAL_ACCURACY: F1 cars are OPEN-COCKPIT with NO ROOF. If you see a roof, canopy,
  windshield, or enclosed cabin on an F1 car = FAIL. Also check for hallucinated faces,
  body parts, or human features merged into car structures or backgrounds = FAIL.
  F1 cars have exposed driver helmets, visible halo device, and open air above the driver.
- TEAM_COLOURS: If team context is provided above, check that the car livery and/or driver
  suit colours roughly match the expected team colours. A red Ferrari car that appears blue = FAIL.
  Minor shade differences are OK. If no team context provided = PASS.
- F1_ACCURACY: Cars shown must be Formula 1 open-cockpit single-seaters with: exposed wheels
  (not covered), front wing, rear wing, halo device, open cockpit. Cars with roofs, enclosed
  cockpits, covered wheels, or that look like Le Mans/GT/road cars = FAIL.
  If no cars shown = PASS.
- CHARACTER_MATCH: If a reference image is provided, does the face match?
  Similar features = PASS. Completely different person = FAIL. No reference = PASS."""

        content_msg = image_content + [{"type": "text", "text": prompt}]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=768,
                messages=[{"role": "user", "content": content_msg}],
            )

            response_text = response.content[0].text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("\n", 1)[1]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()

            result = json.loads(response_text)

            checks = []
            issues = []
            all_passed = True

            for check_name in ["text", "style", "composition", "direction", "physical_accuracy", "team_colours", "f1_accuracy", "character_match"]:
                check_data = result.get(check_name, {})
                passed = check_data.get("passed", True)
                confidence = check_data.get("confidence", 0.5)
                issue = check_data.get("issue")

                checks.append(CheckResult(
                    name=check_name, passed=passed,
                    confidence=confidence, issue=issue,
                ))

                if not passed:
                    all_passed = False
                    if issue:
                        issues.append(f"{check_name}: {issue}")

            return ImageValidation(
                scene_number=scene_number,
                passed=all_passed, checks=checks, issues=issues,
            )

        except Exception as e:
            logger.error(f"Image validation failed: {e}")
            return ImageValidation(
                scene_number=scene_number,
                passed=True,  # Don't block on validation errors
                issues=[f"Validation error (non-blocking): {str(e)}"],
            )

    async def check_video_motion(self, video_path: str) -> bool:
        """Check that the video has motion throughout, not just at the end.

        Extracts one frame per second and compares consecutive pairs.
        FAILS if 3+ consecutive seconds are frozen (mean pixel diff < 5.0).
        This catches videos that are static for seconds 1-4 then only
        move at the end — which the old first-vs-last check missed.
        """
        from PIL import Image
        import numpy as np

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract one frame per second
            subprocess.run(
                ["ffmpeg", "-i", video_path, "-vf", "fps=1",
                 os.path.join(tmpdir, "frame_%02d.png"), "-y"],
                capture_output=True, timeout=30,
            )

            # Load all extracted frames
            frame_files = sorted(
                f for f in os.listdir(tmpdir) if f.startswith("frame_")
            )
            if len(frame_files) < 2:
                logger.warning("Motion check: Could not extract frames")
                return True  # Don't block on extraction failure

            frames = []
            for ff in frame_files:
                img = np.array(
                    Image.open(os.path.join(tmpdir, ff)).convert("RGB")
                )
                frames.append(img)

            # Compare consecutive frame pairs
            diffs = []
            for i in range(len(frames) - 1):
                if frames[i].shape != frames[i + 1].shape:
                    diffs.append(999.0)  # Different size = motion
                    continue
                diff = np.abs(
                    frames[i].astype(float) - frames[i + 1].astype(float)
                )
                diffs.append(diff.mean())

            # Log per-second diffs for debugging
            diff_str = ", ".join(f"s{i+1}-{i+2}:{d:.1f}" for i, d in enumerate(diffs))
            logger.info(f"Motion check per-second diffs: [{diff_str}]")

            # Count consecutive frozen pairs (diff < 5.0)
            max_frozen_streak = 0
            current_streak = 0
            for d in diffs:
                if d < 5.0:
                    current_streak += 1
                    max_frozen_streak = max(max_frozen_streak, current_streak)
                else:
                    current_streak = 0

            # Overall motion check
            mean_diff = sum(diffs) / len(diffs) if diffs else 0
            has_motion = mean_diff > 5.0 and max_frozen_streak < 3

            if not has_motion:
                if max_frozen_streak >= 3:
                    logger.warning(
                        f"Motion check FAILED: {max_frozen_streak} consecutive "
                        f"frozen seconds detected (mean_diff={mean_diff:.1f})"
                    )
                else:
                    logger.warning(
                        f"Motion check FAILED: overall mean_diff={mean_diff:.1f}"
                    )
            else:
                logger.info(
                    f"Motion check PASSED: mean_diff={mean_diff:.1f}, "
                    f"max_frozen_streak={max_frozen_streak}"
                )

            return has_motion


    # ── Audio Validation Methods ──────────────────────────────────────

    async def check_audio_exists(self, video_path: str) -> bool:
        """Check if the video file has an audio track."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0",
                    video_path,
                ],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() == "audio"
        except Exception as e:
            logger.warning(f"Audio exists check failed: {e}")
            return False

    async def check_audio_levels(self, video_path: str) -> tuple[bool, list[float]]:
        """Check per-second RMS audio levels. Fails if 3+ consecutive seconds below -50dB."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=30,
            )
            # Parse RMS levels from stderr
            rms_values = []
            for line in result.stderr.split("\n"):
                if "lavfi.astats.Overall.RMS_level" in line:
                    try:
                        val = float(line.split("=")[-1].strip())
                        rms_values.append(val)
                    except (ValueError, IndexError):
                        continue

            if not rms_values:
                return False, []

            # Check for 3+ consecutive seconds below -50dB (effectively silent)
            consecutive_silent = 0
            max_silent_streak = 0
            for rms in rms_values:
                if rms < -50.0:
                    consecutive_silent += 1
                    max_silent_streak = max(max_silent_streak, consecutive_silent)
                else:
                    consecutive_silent = 0

            passed = max_silent_streak < 3
            if not passed:
                logger.warning(
                    f"Audio levels FAILED: {max_silent_streak} consecutive "
                    f"silent seconds (threshold: 3)"
                )
            return passed, rms_values
        except Exception as e:
            logger.warning(f"Audio levels check failed: {e}")
            return False, []

    async def check_audio_clipping(self, video_path: str) -> bool:
        """Check for audio clipping (peak level > -0.5dB sustained)."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=30,
            )
            clipping_count = 0
            for line in result.stderr.split("\n"):
                if "lavfi.astats.Overall.Peak_level" in line:
                    try:
                        val = float(line.split("=")[-1].strip())
                        if val > -0.5:
                            clipping_count += 1
                    except (ValueError, IndexError):
                        continue

            has_clipping = clipping_count >= 3  # 3+ seconds of clipping
            if has_clipping:
                logger.warning(
                    f"Audio clipping detected: {clipping_count} seconds above -0.5dB"
                )
            return not has_clipping
        except Exception as e:
            logger.warning(f"Audio clipping check failed: {e}")
            return True  # Don't fail on check errors

    async def check_speech_present(
        self, video_path: str, has_dialogue: bool
    ) -> bool:
        """Check if speech is present when dialogue is expected.

        Uses bandpass filter 300Hz-3kHz to isolate speech frequencies,
        then compares energy ratio.
        """
        if not has_dialogue:
            return True  # No dialogue expected, skip check

        try:
            # Get full-band RMS
            full_result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-af", "astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=30,
            )
            # Get speech-band RMS (300Hz-3kHz)
            speech_result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-af", "highpass=f=300,lowpass=f=3000,astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=30,
            )

            def parse_last_rms(output: str) -> float:
                vals = []
                for line in output.split("\n"):
                    if "lavfi.astats.Overall.RMS_level" in line:
                        try:
                            vals.append(float(line.split("=")[-1].strip()))
                        except (ValueError, IndexError):
                            continue
                return sum(vals) / len(vals) if vals else -100.0

            full_rms = parse_last_rms(full_result.stderr)
            speech_rms = parse_last_rms(speech_result.stderr)

            # Convert dB to linear for ratio comparison
            import math
            full_linear = 10 ** (full_rms / 20) if full_rms > -90 else 0.0
            speech_linear = 10 ** (speech_rms / 20) if speech_rms > -90 else 0.0

            ratio = speech_linear / full_linear if full_linear > 0 else 0.0
            passed = ratio >= 0.20  # At least 20% speech energy

            if not passed:
                logger.warning(
                    f"Speech check FAILED: speech/full ratio={ratio:.2f} "
                    f"(threshold: 0.20)"
                )
            return passed
        except Exception as e:
            logger.warning(f"Speech presence check failed: {e}")
            return True  # Don't fail on check errors

    async def check_av_duration_match(self, video_path: str) -> bool:
        """Check that audio and video stream durations match within 500ms."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "stream=codec_type,duration",
                    "-of", "json",
                    video_path,
                ],
                capture_output=True, text=True, timeout=10,
            )
            import json as _json
            data = _json.loads(result.stdout)
            streams = data.get("streams", [])

            video_dur = None
            audio_dur = None
            for s in streams:
                dur = s.get("duration")
                if dur is None:
                    continue
                if s["codec_type"] == "video":
                    video_dur = float(dur)
                elif s["codec_type"] == "audio":
                    audio_dur = float(dur)

            if video_dur is None or audio_dur is None:
                logger.warning("Could not determine A/V durations")
                return True  # Can't check, don't fail

            diff = abs(video_dur - audio_dur)
            passed = diff <= 0.5
            if not passed:
                logger.warning(
                    f"A/V duration mismatch: video={video_dur:.2f}s, "
                    f"audio={audio_dur:.2f}s, diff={diff:.2f}s"
                )
            return passed
        except Exception as e:
            logger.warning(f"A/V duration check failed: {e}")
            return True  # Don't fail on check errors

    async def validate_audio(
        self,
        video_path: str,
        has_dialogue: bool = False,
        audio_description: str = None,
    ) -> "AudioValidation":
        """Run all audio validation checks on a video file.

        Returns an AudioValidation result with per-check details.
        """
        result = AudioValidation()

        # 1. Audio track exists
        result.has_audio_track = await self.check_audio_exists(video_path)
        if not result.has_audio_track:
            result.passed = False
            result.issues.append("No audio track found")
            return result

        # 2. Audio levels (not silent)
        levels_ok, rms_values = await self.check_audio_levels(video_path)
        result.per_second_rms = rms_values
        result.is_silent = not levels_ok
        if result.is_silent:
            result.passed = False
            result.issues.append("Audio is silent for 3+ consecutive seconds")

        # 3. Clipping check
        clipping_ok = await self.check_audio_clipping(video_path)
        result.has_clipping = not clipping_ok
        if result.has_clipping:
            result.passed = False
            result.issues.append("Audio has clipping/distortion")

        # 4. Speech presence (only when dialogue expected)
        if has_dialogue:
            result.speech_detected = await self.check_speech_present(
                video_path, has_dialogue
            )
            if not result.speech_detected:
                result.passed = False
                result.issues.append(
                    "Speech not detected in dialogue scene"
                )
        else:
            result.speech_detected = True  # N/A

        # 5. A/V duration match
        result.duration_match = await self.check_av_duration_match(video_path)
        if not result.duration_match:
            result.passed = False
            result.issues.append("Audio/video duration mismatch > 500ms")

        if result.passed:
            logger.info(f"Audio validation PASSED for {video_path}")
        else:
            logger.warning(
                f"Audio validation FAILED for {video_path}: "
                f"{result.issues}"
            )

        return result


def adapt_prompt_for_validation_failure(scene, validation_result) -> bool:
    """Shared prompt adaptation based on validation failures.

    Used by both jobs.py (single scene regen) and video_pipeline.py (bulk pipeline).
    Returns True if the prompt was modified (worth retrying).
    """
    adapted = False
    prompt = scene.start_frame_prompt or ""

    for check in validation_result.checks:
        if check.passed:
            continue

        if check.name == "text" and "CRITICAL: No text" not in prompt:
            prompt += (
                " CRITICAL: No text, no words, no letters, no numbers, "
                "no watermarks, no writing anywhere in the image. "
                "All surfaces must be clean and text-free."
            )
            adapted = True

        elif check.name == "direction":
            prompt += (
                " ALL vehicles must face the SAME direction. "
                "No car faces the opposite way to the others."
            )
            adapted = True

        elif check.name == "composition":
            import re
            prompt = re.sub(r'(?i)\bCLOSE[- ]?UP\b', 'MEDIUM SHOT', prompt)
            prompt += (
                " Full head, all hair, and both shoulders MUST be visible "
                "with clear space above the head. Camera is far back."
            )
            adapted = True

        elif check.name in ("character", "character_match"):
            prompt += (
                " Character must exactly match the reference image. "
                "Same face, same features, same identity."
            )
            adapted = True

        elif check.name == "physical_accuracy":
            prompt += (
                " F1 cars are OPEN-COCKPIT with NO ROOF. The driver's helmet is "
                "exposed to open air with only a halo device above. No canopy, "
                "no windshield, no enclosed cabin. No hallucinated faces or "
                "body parts in car structures."
            )
            adapted = True

        elif check.name == "team_colours":
            issue_text = check.issue or ""
            prompt += (
                f" CRITICAL COLOUR FIX: {issue_text}. "
                "The car and driver suit colours MUST match the team livery exactly."
            )
            adapted = True

        elif check.name == "f1_accuracy":
            prompt += (
                " F1 cars are OPEN-COCKPIT single-seaters with exposed wheels, "
                "front and rear wings, a halo device, and NO ROOF. "
                "The driver's helmet is visible from outside. "
                "Never draw closed-cockpit, roofed, or Le Mans style cars."
            )
            adapted = True

        elif check.name == "style" and "ANTKF1STYLE" not in prompt:
            prompt = "ANTKF1STYLE " + prompt
            prompt += (
                " Satirical caricature with oversized head and "
                "exaggerated features. NOT photorealistic."
            )
            adapted = True

    if adapted:
        scene.start_frame_prompt = prompt
        logger.info(
            f"Scene {scene.scene_number}: Prompt adapted for retry "
            f"(failures: {[c.name for c in validation_result.checks if not c.passed]})"
        )
    return adapted
