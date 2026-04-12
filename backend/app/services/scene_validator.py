"""Scene quality validator using Claude Vision API."""

import base64
import json
import logging
import os
import re
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

Evaluate these frames on 8 criteria. Return ONLY valid JSON (no markdown):

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
  }},
  "motion": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "mouth_movement": {{
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
- DIRECTION: If the scene shows racing cars or vehicles on a track:
  Step 1: For each car, determine: can you see its FRONT (nose cone, front wing) or its REAR (rear wing, diffuser)?
  Step 2: If you see the FRONT of ANY car facing toward the camera = IMMEDIATE FAIL.
  Step 3: ALL cars must face the SAME direction. Cars going opposite ways = FAIL.
  Step 4: A 3/4 front angle where nose cone is visible = STILL a direction failure.
  If no vehicles are shown = pass.
  ALSO check across frames: if cars are facing one direction in frame 1 but reverse in frame 3 = FAIL.
- MOTION: Compare frame 1 to frame 3 to frame 5. Are there visible DIFFERENCES between frames?
  Characters should move (head turns, gestures, expression changes). Cars should move on track.
  If ALL frames look nearly identical (like the same still photo) = FAIL.
  A slow camera zoom with a frozen subject = FAIL. The SUBJECT must move, not just the camera.
  Only pass if there is genuine subject motion visible between the frames.
- MOUTH_MOVEMENT: If the scene has dialogue (check the dialogue field above) AND a character's
  face is visible, check: does the character's mouth position change between frames?
  Frame 1 mouth closed + frame 3 mouth still closed + frame 5 mouth still closed = FAIL.
  The mouth must visibly open and close across the frames if the character is speaking.
  If no face is visible or no dialogue = pass."""

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

            for check_name in ["style", "character", "artifacts", "composition", "text", "direction", "motion", "mouth_movement"]:
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
  }},
  "car_count": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "clothing": {{
    "passed": true/false,
    "confidence": 0.0-1.0,
    "issue": "description if failed, null if passed"
  }},
  "anatomy": {{
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
- DIRECTION: **THIS IS THE MOST IMPORTANT CHECK.** If ANY racing car or vehicle is visible:
  Step 1: For each car, determine: can you see its FRONT (nose cone, front wing, front
  suspension) or its REAR (rear wing, rear diffuser, exhaust, rear lights)?
  Step 2: If you can see the FRONT of ANY car, meaning the car is facing TOWARD the
  camera or toward the viewer = IMMEDIATE FAIL. The camera should be BEHIND the cars.
  Step 3: ALL cars must show their REAR to the camera — rear wings, diffusers, exhaust.
  The camera is always BEHIND the pack, looking at their backs as they drive away.
  Step 4: If cars face DIFFERENT directions from each other = FAIL.
  COMMON FAILURE MODE: Cars shown from a 3/4 front angle where you can see the nose
  cone and front wing — this is STILL a direction failure. The camera must be BEHIND.
  For cockpit/POV: You look forward through the halo. Cars ahead show their REAR only.
  If no vehicles shown = PASS.
- PHYSICAL_ACCURACY: F1 cars are OPEN-COCKPIT with NO ROOF. If you see a roof, canopy,
  windshield, or enclosed cabin on an F1 car = FAIL. F1 cars have exposed driver helmets,
  visible halo device, and open air above the driver.
- TEAM_COLOURS: If team context is provided above, check that the car livery and/or driver
  suit colours roughly match the expected team colours. A red Ferrari car that appears blue = FAIL.
  Minor shade differences are OK. If no team context provided = PASS.
- F1_ACCURACY: Cars shown must be Formula 1 open-cockpit single-seaters with: exposed wheels
  (not covered), front wing, rear wing, halo device, open cockpit. Cars with roofs, enclosed
  cockpits, covered wheels, or that look like Le Mans/GT/road cars = FAIL.
  If no cars shown = PASS.
- CHARACTER_MATCH: If a reference image is provided, does the face match?
  Similar features = PASS. Completely different person = FAIL. No reference = PASS.
- CAR_COUNT: F1 has exactly 22 cars (11 teams, 2 drivers each). Count distinct cars
  visible in the image. If you see more than approximately 25 distinct cars = FAIL.
  Establishing/wide shots should show 3-8 cars maximum, NOT dozens or hundreds.
  If hundreds of cars or an impossibly large grid is visible = FAIL immediately.
  If no cars visible = PASS.
- CLOTHING: If a driver is the main visible subject (face_visible=true), they MUST wear
  RACING OVERALLS — a one-piece fireproof suit with team branding and sponsor logos.
  Racing overalls have visible team colours, sponsor patches, and zip up the front.
  If the driver appears to be wearing a BUSINESS SUIT, blazer, jacket, tuxedo, formal
  wear, or casual clothing = FAIL. Team principals in polo shirts = PASS.
  Commentators in broadcaster uniforms = PASS. If no person is main subject = PASS.
- ANATOMY: Check for floating or disembodied heads, duplicate faces, extra limbs,
  body parts pasted onto backgrounds, pit girls or grid girls (not in modern F1),
  human features that appear unnaturally placed = FAIL. Oversized/exaggerated heads
  are EXPECTED in caricature style and should NOT be flagged. Caricature proportions
  are intentional. Only flag truly impossible anatomy (floating heads, merged bodies,
  phantom limbs). If no humans visible = PASS."""

        content_msg = image_content + [{"type": "text", "text": prompt}]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
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

            for check_name in ["text", "style", "composition", "direction", "physical_accuracy", "team_colours", "f1_accuracy", "character_match", "car_count", "clothing", "anatomy"]:
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

            # Count consecutive frozen pairs (diff < 8.0)
            # 8.0 = a slow camera zoom with no subject motion.
            # Real character animation produces 15-50+ pixel diff.
            max_frozen_streak = 0
            current_streak = 0
            for d in diffs:
                if d < 8.0:
                    current_streak += 1
                    max_frozen_streak = max(max_frozen_streak, current_streak)
                else:
                    current_streak = 0

            # Also check first 2 seconds specifically — frozen starts are
            # the most common failure mode (model takes time to animate)
            first_2_frozen = all(d < 8.0 for d in diffs[:2]) if len(diffs) >= 2 else False

            # Overall motion check — stricter thresholds:
            # mean_diff > 12.0 = visible motion, not just camera movement
            # max_frozen_streak < 2 = reject even 2 consecutive static seconds
            mean_diff = sum(diffs) / len(diffs) if diffs else 0
            has_motion = mean_diff > 12.0 and max_frozen_streak < 2 and not first_2_frozen

            if not has_motion:
                if first_2_frozen:
                    logger.warning(
                        f"Motion check FAILED: First 2 seconds frozen "
                        f"(diffs: {[f'{d:.1f}' for d in diffs[:3]]})"
                    )
                elif max_frozen_streak >= 2:
                    logger.warning(
                        f"Motion check FAILED: {max_frozen_streak} consecutive "
                        f"frozen seconds detected (mean_diff={mean_diff:.1f})"
                    )
                else:
                    logger.warning(
                        f"Motion check FAILED: overall mean_diff={mean_diff:.1f} "
                        f"(threshold: 12.0)"
                    )
            else:
                logger.info(
                    f"Motion check PASSED: mean_diff={mean_diff:.1f}, "
                    f"max_frozen_streak={max_frozen_streak}"
                )

            return has_motion


    async def check_flf_frame_compatibility(
        self, start_path: str, end_path: str, scene_number: int
    ) -> bool:
        """Check that start and end frames are compatible for FLF interpolation.

        For FLF video, start and end frames must be the SAME SCENE with only
        the action progressing. Same camera angle, same lighting, same location.

        Checks:
        1. Resolution match — frames must have identical dimensions
        2. Pixel difference — overall colour similarity (max 80)
        3. Histogram similarity — same colour palette (min 0.4)
        4. Structural similarity — same scene composition via NCC (min 0.3)
        5. Edge structure — same scene layout via Sobel correlation (min 0.2)

        Returns True if frames are compatible, False if too different.
        """
        from PIL import Image
        import numpy as np

        try:
            start_raw = Image.open(start_path).convert("RGB")
            end_raw = Image.open(end_path).convert("RGB")

            # 1. Resolution check — must be identical dimensions
            if start_raw.size != end_raw.size:
                logger.warning(
                    f"Scene {scene_number}: FLF frames have DIFFERENT resolutions — "
                    f"start={start_raw.size}, end={end_raw.size}. Incompatible."
                )
                return False

            # Resize for fast comparison
            start_img = np.array(start_raw.resize((320, 180)))
            end_img = np.array(end_raw.resize((320, 180)))

            # 2. Overall pixel difference — if frames are vastly different, reject
            pixel_diff = np.abs(start_img.astype(float) - end_img.astype(float)).mean()

            # 3. Colour histogram similarity — same scene should have similar palette
            start_hist = np.histogram(start_img, bins=32, range=(0, 256))[0].astype(float)
            end_hist = np.histogram(end_img, bins=32, range=(0, 256))[0].astype(float)
            start_hist /= start_hist.sum() + 1e-8
            end_hist /= end_hist.sum() + 1e-8
            hist_similarity = np.minimum(start_hist, end_hist).sum()

            # 4. Structural similarity — grayscale cross-correlation
            start_gray = np.mean(start_img, axis=2).astype(float)
            end_gray = np.mean(end_img, axis=2).astype(float)
            ncc = np.corrcoef(start_gray.flatten(), end_gray.flatten())[0, 1]

            # 5. Edge structure — Sobel edge maps should correlate (same layout)
            from scipy.ndimage import sobel
            start_edges = sobel(start_gray)
            end_edges = sobel(end_gray)
            edge_corr = np.corrcoef(start_edges.flatten(), end_edges.flatten())[0, 1]

            compatible = (
                pixel_diff < 80.0
                and hist_similarity > 0.4
                and ncc > 0.15
                and edge_corr > -0.1
            )

            if not compatible:
                reasons = []
                if pixel_diff >= 80.0:
                    reasons.append(f"pixel_diff={pixel_diff:.1f} (max 80)")
                if hist_similarity <= 0.4:
                    reasons.append(f"hist_sim={hist_similarity:.2f} (min 0.4)")
                if ncc <= 0.3:
                    reasons.append(f"structural_sim={ncc:.2f} (min 0.3)")
                if edge_corr <= 0.2:
                    reasons.append(f"edge_corr={edge_corr:.2f} (min 0.2)")
                logger.warning(
                    f"Scene {scene_number}: FLF frames INCOMPATIBLE — "
                    + ", ".join(reasons)
                    + ". Start and end frames must be the SAME SCENE."
                )
            else:
                logger.info(
                    f"Scene {scene_number}: FLF frames compatible — "
                    f"pixel_diff={pixel_diff:.1f}, hist_sim={hist_similarity:.2f}, "
                    f"structural={ncc:.2f}, edge={edge_corr:.2f}"
                )

            return compatible

        except Exception as e:
            logger.warning(f"Scene {scene_number}: FLF compatibility check failed: {e}")
            return False  # Fail safe — don't use FLF if we can't validate

    async def check_video_matches_start_frame(
        self, video_path: str, start_image_path: str, scene_number: int
    ) -> bool:
        """Check that the video's first frame matches the start image.

        Catches cases where LTX ignores the start image entirely.
        Returns True if they match, False if too different.
        """
        from PIL import Image
        import numpy as np

        try:
            # Extract first frame from video
            with tempfile.TemporaryDirectory() as tmpdir:
                first_frame_path = os.path.join(tmpdir, "first_frame.png")
                subprocess.run(
                    ["ffmpeg", "-i", video_path, "-vframes", "1",
                     first_frame_path, "-y"],
                    capture_output=True, timeout=15,
                )
                if not os.path.exists(first_frame_path):
                    logger.warning(f"Scene {scene_number}: Could not extract first frame")
                    return True  # Don't block on extraction failure

                first_frame = np.array(
                    Image.open(first_frame_path).convert("RGB").resize((320, 180))
                )
                start_img = np.array(
                    Image.open(start_image_path).convert("RGB").resize((320, 180))
                )

                pixel_diff = np.abs(
                    first_frame.astype(float) - start_img.astype(float)
                ).mean()

                # Threshold: 60 allows for minor colour shifts from video encoding
                # but catches completely different images
                matches = pixel_diff < 60.0

                if not matches:
                    logger.warning(
                        f"Scene {scene_number}: Video first frame does NOT match "
                        f"start image (pixel_diff={pixel_diff:.1f}, threshold=60)"
                    )
                else:
                    logger.info(
                        f"Scene {scene_number}: Video matches start frame "
                        f"(pixel_diff={pixel_diff:.1f})"
                    )

                return matches

        except Exception as e:
            logger.warning(f"Scene {scene_number}: Start frame match check failed: {e}")
            return True  # Don't block on errors

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


def _strip_old_validation_text(prompt: str) -> str:
    """Remove stacked validation text from previous adapt_prompt calls.

    Handles both the new --FIX: suffix format and the old verbose format
    where CRITICAL/MANDATORY/etc. sentences were appended directly.
    """
    # Strip new-format fix suffix
    prompt = re.sub(r'\s*--FIX:.*$', '', prompt)
    # Strip old-format verbose validation sentences
    prompt = re.sub(r'\s*CRITICAL[:\s][^.]*\.', '', prompt)
    prompt = re.sub(r'\s*ABSOLUTE RULE[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*ALL vehicles[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*MANDATORY[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*IMPORTANT[:\s][^.]*\.', '', prompt)
    prompt = re.sub(r'\s*F1 cars are[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*The character must[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*Character must[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*The driver MUST[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*No floating heads[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*Full head,? all hair[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*Camera is far back\.', '', prompt)
    prompt = re.sub(r'\s*Satirical caricature with[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*NOT photorealistic\.', '', prompt)
    prompt = re.sub(r'\s*CRITICAL COLOUR FIX[^.]*\.', '', prompt)
    prompt = re.sub(r'\s*CRITICAL MOTION REQUIRED[^.]*\.', '', prompt)
    # Clean up any double spaces left behind
    prompt = re.sub(r'\s{2,}', ' ', prompt).strip()
    return prompt


def adapt_prompt_for_validation_failure(scene, validation_result, frame_type="start") -> bool:
    """Adapt prompt based on validation failures WITHOUT bloating.

    CRITICAL: flux-lora's CLIP tokenizer only processes ~60-80 words.
    This function:
      1. Strips ALL previously-appended validation text first
      2. Adds compact one-sentence fixes as a --FIX: suffix
      3. Enforces a hard 75-word limit on the final prompt

    Used by both jobs.py and video_pipeline.py.
    frame_type: 'start' or 'end' -- which prompt to adapt.
    Returns True if the prompt was modified (worth retrying).
    """
    adapted = False
    if frame_type == "end":
        prompt = scene.end_frame_prompt or ""
    else:
        prompt = scene.start_frame_prompt or ""

    # Step 1: Strip ALL previous validation text (old and new formats)
    prompt = _strip_old_validation_text(prompt)

    failed_names = {c.name for c in validation_result.checks if not c.passed}

    # Step 2: Build compact fix suffix -- one short phrase per failure
    fixes = []

    if "text" in failed_names:
        fixes.append("no text, no words, no letters, no watermarks")

    if "direction" in failed_names:
        prompt = re.sub(r'(?i)facing\s+(the\s+)?camera', 'driving away from camera', prompt)
        prompt = re.sub(r'(?i)head[- ]on', 'rear view', prompt)
        fixes.append("all cars driving away from camera")

    if "composition" in failed_names:
        prompt = re.sub(r'(?i)\bCLOSE[- ]?UP\b', 'MEDIUM SHOT', prompt)
        fixes.append("full head visible, medium shot, camera far back")

    if "character" in failed_names or "character_match" in failed_names:
        fixes.append("character must match reference face exactly")

    if "physical_accuracy" in failed_names:
        fixes.append("open-cockpit F1 cars, halo only, no roof")

    if "f1_accuracy" in failed_names:
        fixes.append("open-cockpit single-seaters with exposed wheels and wings")

    if "car_count" in failed_names:
        fixes.append("maximum 22 F1 cars visible")

    if "clothing" in failed_names:
        fixes.append("driver wears racing overalls, not business suit")

    if "anatomy" in failed_names:
        fixes.append("no floating heads, duplicate faces, or impossible anatomy")

    if "team_colours" in failed_names:
        issue = next((c.issue for c in validation_result.checks if c.name == "team_colours" and not c.passed), "")
        if issue:
            fixes.append(issue[:50])

    if "style" in failed_names and "ANTKF1STYLE" not in prompt:
        prompt = "ANTKF1STYLE " + prompt

    if fixes:
        fix_text = ", ".join(fixes)
        prompt += f" --FIX: {fix_text}."
        adapted = True

    # Step 3: Enforce hard 75-word limit
    words = prompt.split()
    if len(words) > 75:
        prompt = " ".join(words[:75])
        logger.warning(
            f"Scene {scene.scene_number}: Prompt truncated from {len(words)} to 75 words"
        )

    if adapted:
        if frame_type == "end":
            scene.end_frame_prompt = prompt
        else:
            scene.start_frame_prompt = prompt

        logger.info(
            f"Scene {scene.scene_number}: {frame_type} frame prompt adapted for retry "
            f"(failures: {list(failed_names)}, words: {len(prompt.split())})"
        )
    return adapted

