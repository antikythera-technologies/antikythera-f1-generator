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

            # Extract 5 frames spread across the clip (catches late-appearing issues)
            frames = await self._extract_frames(video_path, tmpdir)
            if not frames:
                return SceneValidation(
                    scene_number=scene.scene_number,
                    passed=False,
                    issues=["Failed to extract frames from video"],
                )

            # Determine if style check should be skipped (expected drift)
            skip_style = (scene.video_generator or "") in DRIFT_BACKENDS

            return await self._evaluate_frames(frames, scene, skip_style=skip_style)

    async def _extract_frames(self, video_path: str, output_dir: str) -> list[str]:
        """Extract 5 frames spread across the video clip.

        Extracts at 0%, 25%, 50%, 75%, and 95% of the clip to catch
        issues that appear late (like model-generated text at 4s of a 5s clip).
        """
        frame_paths = []

        # Get total frame count
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
            total_frames = 150  # Default: 5s @ 30fps

        # 5 sample points: start, 25%, middle, 75%, near-end
        sample_points = [0, 0.25, 0.5, 0.75, 0.95]
        frame_numbers = [min(int(p * total_frames), max(total_frames - 1, 0)) for p in sample_points]
        # Deduplicate (short clips might have overlapping frame numbers)
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
        # Encode frames as base64
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

        # Build context about the scene
        video_gen = scene.video_generator or "unknown"
        scene_context = f"""Scene {scene.scene_number}:
- Action: {scene.action_description or 'N/A'}
- Dialogue: {scene.dialogue or 'N/A'}
- Scene type: {scene.scene_type or 'N/A'}
- Video generator: {video_gen}"""

        # Build the checks list — skip style for drift-prone backends
        style_instruction = ""
        if skip_style:
            style_instruction = """- STYLE: SKIP this check — set passed=true. This scene uses a video model that naturally
  drifts from caricature to photorealistic during motion. This is expected, not a defect."""
        else:
            style_instruction = """- STYLE: Should be caricature/cartoon style (pass) vs photorealistic (fail).
  Missing LoRA = photorealistic = fail."""

        prompt = f"""You are a quality checker for AI-generated satirical F1 racing videos.
These {len(frame_paths)} frames are sampled across a single 5-second scene (evenly spread from start to end).

{scene_context}

Evaluate these frames on 5 criteria. Return ONLY valid JSON (no markdown):

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
            # Strip markdown code fences if present
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
