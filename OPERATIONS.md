# OPERATIONS — F1 Video Generator

> **Read this before doing ANY work.** This is the operational truth of this system.

## What This System Does

Automated satirical F1 commentary video generator. After each F1 race weekend, the scheduler fires, scrapes news and race results, pulls character personalities and running gags from the database, generates a funny satirical script, renders it as a 2-minute animated video with caricature characters, and publishes to YouTube. **The goal is comedy.** Every run costs real money.

## How It Runs

**Automated.** The scheduler polls every 15 minutes. When a race session ends, it creates an episode and enqueues the pipeline. Every race weekend produces TWO videos:
- **Sprint weekends:** post-sprint + post-race
- **Normal weekends:** post-qualifying + post-race

## The Flow

```
Scheduler fires (race session ended: post-qualifying, post-sprint, or post-race)
  → Sprint weekends: post-sprint + post-race (2 videos)
  → Normal weekends: post-qualifying + post-race (2 videos)
  → Duplicate check: skip if episode already exists for this race + type
  → Reject if race_id is None (root cause guard — bad input never enters pipeline)
  → Create Episode with title format: "{Circuit} {Session}: {Subtitle}"
  → Enqueue pipeline

PHASE 1 — SCRIPT GENERATION (Anthropic Haiku)
  Loads: news articles (with session context injected), race results,
  character personalities (42), running gags (with cooldown enforcement),
  storylines, team data.
  Generates ~26 scenes with: dialogue, action, scene_type, face_visible,
  camera_direction, video_prompt, audio_description, end_frame_delta.
  LLM outputs `subtitle` only — title built from DB: "{Country} {Session}: {Subtitle}".
  Scene durations: variable per dialogue length (calculate_scene_duration()).
  Sanitisation: dialogue → sentence case (capitals = TTS screaming),
  video prompts → strip escalation language, match start_frame_prompt detail.
  End frame prompt = start frame + delta (not standalone), for FLF consistency.

PHASE 2a — IMAGE GENERATION (fal.ai)
  Routes by face_visible:
  - false → flux-lora ($0.035) — LoRA style, no face
  - true + face ref → instant-character ($0.04) — face ref + LoRA, scale=0.3, native landscape 1280×720
  - true + no ref → flux-lora fallback
  Face ref priority: caricature first (better style consistency), real photo fallback.

PHASE 2a-val — IMAGE VALIDATION (Claude Vision, inline)
  8 checks: text, style, composition, direction, physical_accuracy,
  team_colours, f1_accuracy, character_match.
  Critical checks (block video gen): direction, physical_accuracy, car_count, clothing, anatomy.
  Minor checks (warn only): text, style.
  Receives prompt_text + team_context for comparison.
  Up to 2 retries with prompt adaptation per scene.
  Failed critical checks → scene marked FAILED, video NOT generated (saves money).

PHASE 2a-bis — End frames for FLF (ACTION_REPLAY scenes only)
  End frame prompt built from start frame + delta (not standalone description).
  Validated: critical checks + FLF compatibility (pixel_diff < 80, hist_sim > 0.4,
  structural NCC > 0.15, edge_corr > -0.1). Up to 2 retries. Incompatible → no FLF.

PHASE 2b — VIDEO GENERATION (fal.ai, configured backend)
  Prompts built via build_f1_video_prompt() — LTX 2.3 optimized:
  - Camera movement with measurements (dolly, pan, tilt, crane, tracking)
  - camera_direction from script used (mapped via _CAMERA_DIRECTION_MAP)
  - Character animation from personality traits
  - Time-phased choreography per scene type (0-2s, 2-4s, 4-6s beats)
  - Motion directives for non-dialogue scenes (action replays, reactions)
  - Audio prompt: action text prefixed with "Visually:" to prevent LTX narration
  - Negative guidance for artifact reduction
  Duration: variable per scene (based on dialogue length, not fixed 5s).
  Costs tracked per-second via FAL_COST_PER_SECOND.
  10-minute timeout per video generation attempt. 3 retries on transient errors.

PHASE 2d — VIDEO VALIDATION (motion check + audio validation + Claude Vision)
  Motion check (free, ffmpeg pixel diff): mean_diff > 12.0, max 1 frozen second,
  first 2 seconds must not be frozen. Stricter than before (was 5.0/3s).
  Audio validation (free, ffmpeg): audio exists, not silent, no clipping,
  speech present when dialogue expected, A/V duration match.
  Full Claude Vision validation (8 checks including motion + mouth_movement). 1 retry.

PHASE 2c — TTS AUDIO (only if video backend has no native audio)

PHASE 3 — STITCHING (ffmpeg concatenation)

PHASE 4 — YOUTUBE UPLOAD (currently disabled for manual review)
```

## Rules

### THE NON-NEGOTIABLES

**FIX THE ACTUAL PROBLEM, NOT THE SYMPTOM.** When something breaks, find the root cause and fix it there. Do not patch around it, do not add a workaround, do not suppress the error. If data is wrong, fix where the data is created. If a value is None, reject it at the entry point — do not add `if x is None` guards six layers deep. Research properly before implementing. Read the docs. Read the code. Understand the problem. Then fix it once, correctly.

**THIS IS A FULLY AUTOMATED SYSTEM. THERE IS NO HUMAN IN THE LOOP.** The scheduler fires. News is scraped. Jokes are loaded. Database is queried. Prompts are built. Images are generated. Videos are generated. Videos are uploaded. End to end. No human answers questions. No human retries failures. No human fixes bad data. Every single change must be evaluated from the scheduler's perspective: "Will this work when nobody is watching?" If the answer is no, the change is wrong.

### Operational Rules

1. **Fix the pipeline, NEVER fix individual scenes.** Automated system. Scene fixes are overwritten next run.
2. **Shared service layer enforces feature parity.** Image gen, video gen, validation, and cost tracking live in `services/scene_image_service.py`, `scene_video_service.py`, `scene_orchestrator.py`, and `cost_tracker.py`. Both `video_pipeline.py` and `jobs.py` call these shared functions — never duplicate logic between them.
3. **Never touch scene audio.** Native audio from video backends is sacred.
4. **Never regenerate existing episodes.** Scheduler checks for duplicates. API returns 409.
5. **Never state API capabilities without verifying.** Test or check docs first — do proper research.
6. **ANY capitals in dialogue = TTS screaming.** Sentence case only. F1/DRS/FIA preserved.
7. **Content is king.** Script must be funny, topical, and use all available context. 6-7 characters per episode (3-4 main + 2-3 cameos). Both Croft AND Brundle in every episode.
8. **Never generate scenes or spend money without explicit user instruction.**
9. **ALL data in database.** Never JSON files on disk.
10. **NEVER blind-fire the pipeline.** Dry-run verify BEFORE spending money.

## External Services & Costs

| Service | What For | Cost Per Use |
|---------|----------|-------------|
| fal.ai flux-lora | Scene images (action/landscape) | $0.035/image |
| fal.ai instant-character | Scene images (character faces) | $0.04/image |
| fal.ai LTX 2.3 | Video clips (active backend) | $0.06/sec (~$0.36/6s clip) |
| fal.ai Ovi | Video clips | $0.04/sec (~$0.20/5s clip) |
| fal.ai Kling 3.0 | Video clips (higher quality) | $0.07-$0.14/sec |
| Anthropic Haiku | Script generation | ~$0.02/episode |
| Anthropic Claude Vision | Image + video validation (10 checks/scene) | ~$0.003-$0.015/check |
| Edge TTS | Voice generation | Free |
| MinIO | Object storage | Self-hosted |

**Full episode cost estimate:** ~$10-15 with LTX (variable durations), ~$15-25 with Kling. Costs tracked per-scene via `FAL_COST_PER_SECOND` × duration.

## Key Decisions

- **instant-character over flux-general**: flux-general's IP-Adapter bleeds face into background. instant-character preserves identity at scale=0.3, native landscape 1280×720 (no post-processing).
- **Face ref priority**: Caricature first (better style consistency with LoRA), real photo fallback.
- **LTX 2.3 video prompts**: Image-to-video prompts describe temporal evolution, not static image. Explicit camera verbs with measurements. Time-phased choreography (0-2s/2-4s/4-6s beats per scene type). Action text prefixed "Visually:" to prevent LTX narration.
- **camera_direction from script**: LLM generates per-scene camera direction, mapped to LTX-optimized language with measurements via `_CAMERA_DIRECTION_MAP`. Falls back to scene-type defaults.
- **Image validation**: 8 checks (start frames) + 8 checks (video). Critical (direction, physical_accuracy, car_count, clothing, anatomy) blocks video gen. Minor (text, style) warns only. Video gets 2 new checks: motion (subject must move) and mouth_movement (face must animate during dialogue).
- **FLF frame compatibility**: End frames validated against start frames (pixel diff, histogram similarity, structural NCC, edge correlation). Incompatible frames → FLF skipped gracefully.
- **Deterministic titles**: LLM outputs `subtitle` only. Title built from DB: "{Country} {Session}: {Subtitle}". `EpisodeType.session_label` is source of truth.
- **Variable scene durations**: `calculate_scene_duration()` sizes each clip to dialogue length instead of fixed 5s. Prevents dialogue cutoff and reduces cost on short scenes.
- **Gag cooldown system**: Running gags have `cooldown_races` — gag won't be offered to script gen until N races have passed since last use.
- **Timeouts**: Video gen 10min, image gen 5min, card images 3min. Prevents scheduler hangs from stuck fal.ai queues.
- **Episode-specific title cards**: Stitcher uses episode storyline to generate contextual title card background (not generic aerial shot).
- **Self-hosted LTX blocked**: ComfyUI integration failed (2026-03-12). fal.ai LTX is active backend.
- **YouTube auto-upload disabled**: Manual review until pipeline quality validated.
- **Scheduler**: post-qualifying (normal weekends) + post-sprint (sprint weekends) + post-race (always). Two videos per race weekend.
- **Modular service layer (2026-04-12)**: Extracted shared logic from video_pipeline.py and jobs.py into reusable services. Pipeline is a thin orchestrator (~1300 lines, down from ~3000). Jobs are thin RQ wrappers (~880 lines, down from ~1900). No duplicated business logic. Circular dependency eliminated.

## Known Issues

- YouTube upload code exists but auto-upload disabled pending quality validation
- RunPod ComfyUI pod still needed for character caricature generation only
