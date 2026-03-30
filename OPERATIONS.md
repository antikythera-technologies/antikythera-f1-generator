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
  → Create Episode record, enqueue pipeline

PHASE 1 — SCRIPT GENERATION (Anthropic Haiku)
  Loads: news articles, race results, character personalities (42),
  running gags (with cooldowns), storylines, team data.
  Generates ~26 scenes with: dialogue, action, scene_type, face_visible,
  camera_direction, video_prompt, audio_description.
  Sanitisation: dialogue → sentence case (capitals = TTS screaming),
  video prompts → strip escalation language (crescendo, dramatically).

PHASE 2a — IMAGE GENERATION (fal.ai)
  Routes by face_visible:
  - false → flux-lora ($0.035) — LoRA style, no face
  - true + face ref → instant-character ($0.04) — face ref + LoRA, scale=0.3
  - true + no ref → flux-lora fallback

PHASE 2a-val — IMAGE VALIDATION (Claude Vision, inline)
  8 checks: text, style, composition, direction, physical_accuracy,
  team_colours, f1_accuracy, character_match.
  Receives prompt_text + team_context for comparison.
  Up to 2 retries with prompt adaptation per scene.
  Failed images → scene marked FAILED, video NOT generated (saves money).

PHASE 2a-bis — End frames for FLF (ACTION_REPLAY scenes only)

PHASE 2b — VIDEO GENERATION (fal.ai, configured backend)
  Prompts built via build_f1_video_prompt() — LTX 2.3 optimized:
  - Camera movement with measurements (dolly, pan, tilt, crane, tracking)
  - camera_direction from script used (was previously ignored)
  - Character animation from personality traits
  - Temporal evolution focus (not redescribing the static image)
  - Negative guidance for artifact reduction
  - ~70 words per prompt (was ~180)

PHASE 2d — VIDEO VALIDATION (motion check + audio validation + Claude Vision)
  Motion check (free, ffmpeg pixel diff).
  Audio validation (free, ffmpeg): audio exists, not silent, no clipping,
  speech present when dialogue expected, A/V duration match.
  Full Claude Vision validation with 1 retry.

PHASE 2c — TTS AUDIO (only if video backend has no native audio)

PHASE 3 — STITCHING (ffmpeg concatenation)

PHASE 4 — YOUTUBE UPLOAD (currently disabled for manual review)
```

## Rules

1. **Fix the pipeline, NEVER fix individual scenes.** Automated system. Scene fixes are overwritten next run.
2. **Feature parity between pipeline and jobs.** `video_pipeline.py` and `jobs.py` must have identical image routing, video prompt wrapping, validation, and TTS logic.
3. **Never touch scene audio.** Native audio from video backends is sacred.
4. **Never regenerate existing episodes.** Scheduler checks for duplicates. API returns 409.
5. **Never state API capabilities without verifying.** Test or check docs first.
6. **ANY capitals in dialogue = TTS screaming.** Sentence case only. F1/DRS/FIA preserved.
7. **Content is king.** Script must be funny, topical, and use all available context. 6-7 characters per episode (3-4 main + 2-3 cameos). Both Croft AND Brundle in every episode.
8. **Never generate scenes or spend money without explicit user instruction.**
9. **ALL data in database.** Never JSON files on disk.

## External Services & Costs

| Service | What For | Cost Per Use |
|---------|----------|-------------|
| fal.ai flux-lora | Scene images (action/landscape) | $0.035/image |
| fal.ai instant-character | Scene images (character faces) | $0.04/image |
| fal.ai LTX 2.3 | Video clips (active backend) | $0.30/clip |
| fal.ai Ovi | Video clips | $0.20/clip |
| fal.ai Kling 3.0 | Video clips (higher quality) | $0.42-$0.84/clip |
| Anthropic Haiku | Script generation | ~$0.02/episode |
| Anthropic Claude Vision | Image + video validation | ~$0.003-$0.015/check |
| Edge TTS | Voice generation | Free |
| MinIO | Object storage | Self-hosted |

**Full episode cost estimate:** ~$10-12 with LTX, ~$15-25 with Kling.

## Key Decisions

- **instant-character over flux-general**: flux-general's IP-Adapter bleeds face into background. instant-character preserves identity at scale=0.3.
- **LTX 2.3 video prompts**: Image-to-video prompts describe temporal evolution, not static image. Explicit camera verbs with measurements. ~70 words, not ~180. Based on official LTX prompting guide.
- **camera_direction from script**: LLM generates per-scene camera direction, mapped to LTX-optimized language with measurements via `_CAMERA_DIRECTION_MAP`. Falls back to scene-type defaults.
- **Inline image validation**: Validates BEFORE expensive video gen. 8 checks including team colours and F1 accuracy. Shared `adapt_prompt_for_validation_failure()` in scene_validator.py.
- **Self-hosted LTX blocked**: ComfyUI integration failed (2026-03-12). fal.ai LTX is active backend.
- **YouTube auto-upload disabled**: Manual review until pipeline quality validated.
- **Scheduler**: post-qualifying (normal weekends) + post-sprint (sprint weekends) + post-race (always). Two videos per race weekend.

## Known Issues

- YouTube upload code exists but auto-upload disabled pending quality validation
- RunPod ComfyUI pod still needed for character caricature generation only
- Worker has a connection leak bug in _scheduler_poll_loop (idle-in-transaction connections)
