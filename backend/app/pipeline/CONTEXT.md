# Pipeline Workspace Context

> Layer 2 context -- read this when working on scene generation, video generation, or the pipeline itself.

## BEFORE YOU CHANGE ANYTHING

This pipeline runs from the scheduler with zero human intervention. Scrape news → load gags → query DB → build prompts → generate images → generate video → upload. Nobody is there to answer questions, retry failures, or fix bad data.

**Every change you make: ask "will this work when nobody is watching?"** If yes, proceed. If no, rethink.

**Fix the actual problem, not the symptom.** If data is wrong, fix where the data is produced. If a value is None, reject it at the entry point. Do not add defensive checks deep in the pipeline to paper over upstream bugs. Research properly — read docs, read code, understand the problem — then fix it once, correctly.

## What This Workspace Does

The video generation pipeline -- a thin orchestrator (~1300 lines) that calls shared service functions. Each episode generates ~26 scenes with variable durations.

`video_pipeline.py` handles Phase 1 (script generation) and orchestration. All scene-level work (image gen, validation, video gen) is delegated to `scene_orchestrator.process_scene()` in the shared service layer.

## Pipeline Phases

**Guard:** Pipeline refuses to run if `race_id` is None (root cause rejection at episode creation).

1. **Script Generation** -- Anthropic Haiku. Unique to pipeline (not shared). News articles enriched with session context. Running gags filtered by cooldown. LLM outputs `subtitle` only — title built from DB facts.
2. **Scene Processing** -- Delegated to `scene_orchestrator.process_scene()` per scene:
   - Image gen via `scene_image_service.generate_scene_image()` (flux-lora / instant-character routing)
   - Image validation (8 checks, critical blocks, minor warns, self-correcting retries)
   - End frame gen for FLF (ACTION_REPLAY only, compatibility check)
   - Video gen via `scene_video_service.generate_scene_video()` (fal.ai, LTX 2.3 optimized prompts)
   - Video validation (motion check + Claude Vision, self-correcting retries)
   - Audio validation (non-blocking)
3. **TTS Audio** -- Edge TTS + mux, only if video backend has no native audio.
4. **Stitching** -- ffmpeg concatenation.
5. **YouTube Upload** -- Currently DISABLED.

## Image Generation Routing (in `scene_image_service.py`)

| Scene Property | Image Backend | What Happens |
|---|---|---|
| `face_visible=False` | **flux-lora** | LoRA style only, racing direction rules, no character face |
| `face_visible=True` + face ref | **instant-character** | Face ref + LoRA, scale=0.8, portrait 720x1280 → blur-pad landscape |
| `face_visible=True` + no face ref | **flux-lora fallback** | LoRA + detailed prompt description |

## Video Prompt Builder (in `fal_video_generator.py`)

`build_f1_video_prompt()` follows LTX 2.3 image-to-video best practices:
- Does NOT redescribe the static image — LTX already sees it
- Explicit camera verbs with measurements
- Uses `camera_direction` from Scene DB via `_CAMERA_DIRECTION_MAP`
- Scene-type camera defaults (8 types)
- Character animation from personality traits
- Time-phased choreography per scene type (0-2s/2-4s/4-6s beats)
- Audio prompt: action text prefixed with "Visually:" to prevent LTX narration
- Negative guidance for artifact reduction

## Key Files

| File | Purpose |
|------|---------|
| `video_pipeline.py` | Thin orchestrator — script gen + delegates to shared services |
| `flf_router.py` | Determines which scenes get end frames (ACTION_REPLAY only) |
| `../services/scene_orchestrator.py` | Full scene lifecycle (image → validate → video → validate) |
| `../services/scene_image_service.py` | Image gen with flux-lora / instant-character routing |
| `../services/scene_video_service.py` | Video gen via fal.ai with prompt building |
| `../services/cost_tracker.py` | Shared cost logging + episode cost aggregation |
| `../services/fal_video_generator.py` | `build_f1_video_prompt()` + fal.ai video gen (8 backends) |
| `../services/scene_validator.py` | Image + video validation + `adapt_prompt_for_validation_failure()` |
| `../services/script_generator.py` | Anthropic Haiku script gen + dialogue/prompt sanitisation |
| `../services/tts_generator.py` | Edge TTS + 42 character voice mappings |
| `../jobs.py` | Thin RQ wrappers — call same shared services as pipeline |
