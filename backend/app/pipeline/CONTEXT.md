# Pipeline Workspace Context

> Layer 2 context -- read this when working on scene generation, video generation, or the pipeline itself.

## What This Workspace Does

The video generation pipeline -- 5 sequential phases that turn a race event into a 2-minute satirical F1 video. Each episode generates ~26 x 5-second scenes.

## Pipeline Phases

1. **Script Generation** -- Anthropic Haiku generates scene scripts (dialogue, action, audio descriptions, face_visible flags) given race context and character personalities.
2. **Video Clip Generation** -- Three sub-phases:
   - Phase 2a: Generate scene images via fal.ai (flux-lora OR instant-character based on scene type).
   - Phase 2a-bis: Generate end frames for FLF-capable video backends.
   - Phase 2b: Generate videos from images via configured fal.ai video backend.
   - Phase 2c: Generate TTS audio (Edge TTS) and mux -- only for non-AV backends. Skipped when video backend produces native audio.
3. **Stitching** -- ffmpeg concatenates all clips into final video (libx264, CRF 23, aac audio).
4. **YouTube Upload** -- OAuth2 resumable upload with metadata (title, description, tags). Currently DISABLED (auto-upload off).
5. **Cleanup** -- Delete MinIO assets older than retention policy.

## Image Generation Routing (CRITICAL)

The pipeline routes scene images to different fal.ai backends based on `face_visible` field:

| Scene Property | Image Backend | What Happens |
|---|---|---|
| `face_visible=False` (ACTION_REPLAY, ESTABLISHING) | **flux-lora** | LoRA style only, racing direction rules, no character face |
| `face_visible=True` + face ref exists | **instant-character** | Face ref + LoRA, identity preservation, scale=0.3, 1280x1280->720 crop |
| `face_visible=True` + no face ref file | **flux-lora fallback** | LoRA + detailed prompt description |

Additional image prompt features:
- Close-up -> MEDIUM SHOT rewriting (prevents head cropping)
- "WIDE MEDIUM SHOT, camera 5 meters away" framing guard for character scenes
- Team overalls fallback when no episode appearance set
- Racing direction rules (all cars same direction, show rear wings)
- POV/cockpit detection for in-car shots
- Episode appearance/clothing consistency from episode-level metadata
- Negative prompts for head cropping prevention (instant-character)

**RULE: Image generation routing MUST have feature parity between `video_pipeline.py::_get_scene_image_fal` and `jobs.py::_async_scene_image`. If one has a feature, the other must too.**

## Video Backends

Selected by `VIDEO_GENERATOR_DEFAULT` in `config.py`. 8 options:

| Backend | Model | Cost/clip | Status |
|---------|-------|-----------|--------|
| `fal-ovi` | fal.ai Ovi | $0.20 | Active |
| `fal-ltx` | fal.ai LTX 2.3 | $0.30 | Available |
| `fal-kling-std` | fal.ai Kling 3.0 Std | $0.42 | Available |
| `fal-kling-pro` | fal.ai Kling 3.0 Pro | $0.42 | Available |
| `fal-kling-o1-flf` | fal.ai Kling O1 (FLF) | $0.56 | Available |
| `fal-vidu-q1-flf` | fal.ai Vidu Q1 (FLF) | $0.50 | Available |
| `fal-wan-flf` | fal.ai Wan (FLF) | $0.50 | Available |
| `ovi` | Self-hosted RunPod Ovi | ~free | Legacy (RunPod pod needed) |

## Key Files

| File | Purpose |
|------|---------|
| `video_pipeline.py` | Orchestrator -- runs all 5 phases, routes image backends |
| `flf_router.py` | Determines which scenes get end frames (FLF-capable backends) |
| `../services/fal_video_generator.py` | fal.ai video gen (all fal-* backends) |
| `../services/image_generator.py` | ComfyUI image gen (legacy, used for character caricatures) |
| `../services/script_generator.py` | Anthropic Haiku script generation |
| `../services/tts_generator.py` | Edge TTS speech generation + 42 character voice mappings |
| `../services/audio_mixer.py` | Mux TTS audio onto video clips via ffmpeg |
| `../services/stitcher.py` | ffmpeg concatenation |
| `../services/storage.py` | MinIO object storage |
| `../services/scene_validator.py` | Post-gen validation (ffmpeg screenshots + Claude Vision) |
| `../jobs.py` | RQ job wrappers for scene regen, stitch, validate, YouTube upload |
| `../worker.py` | RQ worker + scheduler poll (with duplicate episode prevention) |
| `../config.py` | All settings |

## Duplicate Episode Prevention

`worker.py::_process_pending_jobs` checks `Episode.race_id + episode_type` before creating. If an episode already exists, the scheduled job is marked COMPLETED and skipped. The API endpoint `episodes.py::generate_episode` also has this guard (409 conflict unless `force=true`).

## MinIO Storage Paths

```
f1-scene-images/race_{id:03d}/episode_{id}/scene_{num:02d}_{suffix}.png
f1-video-clips/race_{id:03d}/episode_{id}/scene_{num:02d}.mp4
f1-final-videos/race_{id:03d}/episode_{id}/final.mp4
```

## Video Prompt F1 Context (CRITICAL)

Every video prompt is wrapped via `build_f1_video_prompt()` in `fal_video_generator.py`. This injects:
- Scene-type-specific F1 environment (pit garage, podium, racing circuit)
- Team colours from DB (car_description, overalls_description)
- Anti-drift footer: "Maintain exact clothing/setting, only F1 open-cockpit cars"
- Lip movement instruction (only when face_visible=True)
- Voiceover narration prefix (when face_visible=False + dialogue exists — prevents hallucinated faces in cockpit/action scenes)

**RULE: Video prompt wrapping MUST have feature parity between `video_pipeline.py::_generate_video_clips_fal` and `jobs.py::_async_scene_video`.**

## Current Development State

Pipeline video prompts fixed (2026-03-26): All video prompts now include F1 context, team colours from DB, and correct dialogue handling (face_visible controls lip movement vs voiceover narration). Image routing fixed (2026-03-23): instant-character for character scenes, flux-lora for action/landscape. Stitching works. YouTube upload disabled for now (manual review before publishing).
