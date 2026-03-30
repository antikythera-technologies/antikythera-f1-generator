# Next Session Handover — F1 Video Generator

## Read First
- `OPERATIONS.md` — full pipeline flow, rules, costs
- `backend/app/pipeline/CONTEXT.md` — pipeline phases
- This document

## Current State (2026-03-30)

### Episode 9: "Kimi's China Shock: The Kid Conquers Shanghai"
- **Status**: COMPLETED (stitched, NOT yet uploaded to YouTube)
- **DB ID**: 9 (NOT 7 — Episode 7 is the Sprint episode, already published)
- **26/26 scenes generated**, validated, and stitched
- **Final video**: `f1-final-videos/race_002/episode_9/final.mp4` (208s, 98MB)
- **Total cost**: ~$8.80
- **Scene 10 was re-done** (missing ambient audio), episode re-stitched
- **Stitch may still be running** — check `episodes.status` for episode 9. If `completed`, it's done.

### Japanese GP Scheduler
- Job ID 6 (`scheduled_jobs` table) was **cancelled** to prevent auto-firing while we work manually
- When ready for the Japanese GP episode, set it back to `scheduled` or create the episode manually

### Server Issue Found & Fixed
- User's ISP changed IP from `41.23.65.243` to `105.246.69.207`
- UFW rule added: `sudo ufw allow from 105.246.69.207 to any port 5432`
- Also found 15 leaked "idle in transaction" PostgreSQL connections from the scheduler worker — killed them
- The worker has a connection leak bug in its poll loop that needs fixing (not done yet)

---

## Pipeline Fixes Made This Session

All fixes are in the working tree (uncommitted). Key files modified:

### 1. Voice Description Screaming Fix (`backend/app/services/fal_video_generator.py`)
- **Function**: `_sanitize_voice_description()` — new module-level function
- Strips "SCREAMING", "crescendo", "volcanic", "throat-shredding" from character personality voice descriptions
- LTX generates audio from prompt text; personality words caused literal screaming

### 2. LTX Prompt Structure Fix (`backend/app/services/fal_video_generator.py`)
- **Function**: `_args_ltx()` — modified
- Only dialogue + camera + lip sync + neg guidance in the prompt. Video_prompt descriptive text excluded
- LTX vocalizes the ENTIRE prompt; descriptive text became extra narration

### 3. STATIC Camera Override (`backend/app/services/fal_video_generator.py`)
- **Function**: `_resolve_camera_movement()` — modified
- STATIC on talking scenes overridden to scene-type default (pan, dolly)
- LTX needs camera movement to animate characters

### 4. Stronger Lip Sync Instructions (`backend/app/services/fal_video_generator.py`)
- **Function**: `build_f1_video_prompt()` — modified
- TWO_SHOT/OVER_THE_SHOULDER get two-character animation cues
- Note: LTX can't animate background faces — use TALKING_HEAD if speaker would be small

### 5. Direction Pattern Expansion (`backend/app/services/script_generator.py`)
- **Function**: `sanitize_scene_prompts()` — expanded with 9 new patterns
- "approaching finish", "accelerating toward", "front wings visible", etc.

### 6. Prompt Sanitization During Regeneration (`backend/app/jobs.py`)
- `sanitize_prompt_text()` runs on stored prompts in `_async_scene_image()` and `_async_scene_video()`

### 7. Standalone Prompt Sanitizer (`backend/app/services/script_generator.py`)
- **Function**: `sanitize_prompt_text()` — new, works on plain strings

### 8. Proper Noun Preservation (`backend/app/services/script_generator.py`)
- `_F1_PROPER_NOUNS` list (~80 entries) restored after lowercase conversion in `sanitize_dialogue()`

### 9. TWO_SHOT / OVER_THE_SHOULDER Composition Rules (`backend/app/services/script_generator.py`)
- LLM system prompt now instructs speaker-dominant composition

### 10. Race ID Fix (`backend/app/jobs.py`)
- `_async_scene_image()` and `_async_scene_video()` look up episode's `race_id` instead of hardcoded 0

### 11. Per-Second Motion Check (`backend/app/services/scene_validator.py`)
- `check_video_motion()` rewritten — frame per second, fails on 3+ consecutive frozen seconds

### 12. Stronger Overalls Instruction (`backend/app/jobs.py`)
- "MANDATORY CLOTHING" prefix forces team race suit, prevents business suit generation

---

## What Needs To Be Built: Audio Validation

### Location
`backend/app/services/scene_validator.py` — new methods on `SceneValidator`

### Checks to Implement

#### 1. Audio Track Exists
```python
async def check_audio_exists(self, video_path: str) -> bool:
```
- `ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0`
- Free (ffprobe)

#### 2. Not Silent (per-second RMS)
```python
async def check_audio_levels(self, video_path: str) -> tuple[bool, list[float]]:
```
- `ffmpeg -i video -af astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level -f null -`
- FAIL if 3+ consecutive seconds below -50dB
- Free (ffmpeg)

#### 3. No Clipping/Distortion
```python
async def check_audio_clipping(self, video_path: str) -> bool:
```
- Check `Peak_level` > -0.5dB sustained = clipping
- Free (ffmpeg)

#### 4. Speech Present When Expected
```python
async def check_speech_present(self, video_path: str, has_dialogue: bool) -> bool:
```
- Bandpass 300Hz-3kHz, measure energy ratio
- FAIL if < 20% speech energy when dialogue expected
- Free (ffmpeg)

#### 5. Audio-Video Duration Match
```python
async def check_av_duration_match(self, video_path: str) -> bool:
```
- FAIL if A/V duration diff > 500ms
- Free (ffprobe)

#### Orchestrator
```python
async def validate_audio(self, video_path: str, has_dialogue: bool = False,
                         audio_description: str = None) -> AudioValidation:
```

#### Dataclass
```python
@dataclass
class AudioValidation:
    passed: bool
    has_audio_track: bool
    is_silent: bool           # True = bad
    has_clipping: bool        # True = bad
    speech_detected: bool     # False when expected = bad
    duration_match: bool
    per_second_rms: list[float]
    issues: list[str]
```

### Integration Points
1. Manual generation loop — after motion check, run audio validation, retry if fails
2. `_async_scene_video()` in `jobs.py` — after upload, validate audio
3. `video_pipeline.py` Phase 2d — alongside motion check
4. Update `OPERATIONS.md` Phase 2d documentation

---

## Other Pending Items

1. **YouTube upload for Episode 9** — Ready to upload. Use `_async_youtube_upload(episode_id=9)`
2. **Japanese GP intro** — Cherry blossoms / Japan theme for NEXT episode's title card
3. **Worker connection leak** — `_scheduler_poll_loop()` leaks idle-in-transaction connections
4. **Commit all changes** — 12 pipeline fixes uncommitted
5. **Re-index codebase** — `mcp__jcodemunch__index_folder` after commit

---

## Key Lessons (non-negotiable)

1. **NEVER touch published episodes** — check `episodes.status` first
2. **Episode 9 = Chinese Race, Episode 7 = Sprint (published)**
3. **LTX vocalizes entire prompt** — only dialogue as speech content
4. **LTX can't animate background faces** — speaker must be dominant/foreground
5. **STATIC camera = frozen characters** — override to dolly/pan for talking scenes
6. **"Approaching" = cars facing camera** — sanitize ALL direction language
7. **All fixes in pipeline code** — never manual prompt patches
8. **Validate everything** — image (direction) → video (motion) → audio (next)
9. **DB table is `episode_scenes`** not `scenes`
