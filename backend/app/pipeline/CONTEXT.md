# Pipeline Workspace Context

> Layer 2 context -- read this when working on scene generation, video generation, or the pipeline itself.

## What This Workspace Does

The video generation pipeline -- 5 sequential phases that turn a race event into a 2-minute satirical F1 video. Each episode generates ~26 x 5-second scenes.

## Pipeline Phases

1. **Script Generation** -- Anthropic Haiku generates scene scripts (dialogue, action, audio descriptions, face_visible flags, camera_direction) given race context and character personalities. Sanitises dialogue to sentence case (capitals = TTS screaming) and strips video prompt escalation language.
2. **Image Generation** (fal.ai) -- Routes by face_visible: flux-lora for landscape/action, instant-character for character faces.
3. **Image Validation** (Claude Vision, inline) -- 8 checks before expensive video gen: text, style, composition, direction, physical_accuracy, team_colours, f1_accuracy, character_match. Receives prompt_text + team_context. Up to 2 retries with shared `adapt_prompt_for_validation_failure()`. Failed images → scene FAILED, no video generated.
4. **End Frames** (FLF) -- ACTION_REPLAY scenes only on FLF-capable backends.
5. **Video Generation** (fal.ai) -- LTX 2.3 optimized prompts via `build_f1_video_prompt()`.
6. **Video Validation** -- Motion check (free) + audio validation (5 ffmpeg checks, free) + Claude Vision. 1 retry.
7. **TTS Audio** -- Edge TTS + mux, only if video backend has no native audio.
8. **Stitching** -- ffmpeg concatenation.
9. **YouTube Upload** -- Currently DISABLED.

## Image Generation Routing (CRITICAL)

| Scene Property | Image Backend | What Happens |
|---|---|---|
| `face_visible=False` | **flux-lora** | LoRA style only, racing direction rules, no character face |
| `face_visible=True` + face ref | **instant-character** | Face ref + LoRA, scale=0.3, 1280x1280→720 crop |
| `face_visible=True` + no face ref | **flux-lora fallback** | LoRA + detailed prompt description |

**RULE: Image routing MUST have feature parity between `video_pipeline.py` and `jobs.py::_async_scene_image`.**

## Video Prompt Builder (CRITICAL — LTX 2.3 Optimized)

`build_f1_video_prompt()` in `fal_video_generator.py` follows LTX 2.3 image-to-video best practices:
- **Does NOT redescribe the static image** — LTX already sees it
- **Explicit camera verbs with measurements** — "Dolly-in 0.3 meters over 6 seconds, 50mm lens"
- **Uses `camera_direction`** from Scene DB — mapped via `_CAMERA_DIRECTION_MAP` to LTX-optimized language
- **Scene-type camera defaults** — 8 types with appropriate lens, distance, duration
- **Character animation** from personality traits (signature_expression, signature_pose)
- **One ambient motion element** per scene type (LED screens, crowd, confetti, etc.)
- **Negative guidance** — "No face warping, no object duplication, no flickering"
- **~70 words** per prompt (was ~180)

New params: `camera_direction`, `character_animation`, `livery_description` — all optional.

**RULE: Video prompt construction MUST have feature parity between `video_pipeline.py` and `jobs.py::_async_scene_video`.**

## Key Files

| File | Purpose |
|------|---------|
| `video_pipeline.py` | Orchestrator -- all phases, image routing, validation |
| `flf_router.py` | Determines which scenes get end frames (ACTION_REPLAY only) |
| `../services/fal_video_generator.py` | `build_f1_video_prompt()` + fal.ai video gen (8 backends) |
| `../services/scene_validator.py` | Image validation (8 checks) + video validation + shared `adapt_prompt_for_validation_failure()` |
| `../services/script_generator.py` | Anthropic Haiku script gen + dialogue/prompt sanitisation |
| `../services/tts_generator.py` | Edge TTS + 42 character voice mappings |
| `../jobs.py` | RQ job wrappers — single scene regen, stitch, validate |

## Current Development State

Pipeline LTX 2.3 prompt enhancement deployed (2026-03-27). Comedy overhaul (2026-03-30): 6-7 characters per episode (main cast + cameos), Croft + Brundle mandatory in every episode, 10 comedy techniques enforced, post-qualifying episode type added. Audio validation (5 ffmpeg checks) integrated in Phase 2d. Every race weekend now produces 2 videos (qualifying/sprint + race).
