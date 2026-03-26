# OPERATIONS — F1 Video Generator

> **Read this before doing ANY work.** This is the operational truth of this system.

## What This System Does

Automated satirical F1 commentary video generator. After each F1 race weekend, the scheduler fires, scrapes news and race results, pulls character personalities and running gags from the database, generates a funny satirical script, renders it as a 2-minute animated video with caricature characters, and publishes to YouTube. **The goal is comedy.** This is a satirical show — it must be funny, topical, and build on recurring jokes across episodes. Every run costs real money.

## How It Runs

**Automated.** The scheduler polls every 15 minutes. When a race session ends (FP2, Sprint, Race), it creates an episode and enqueues the pipeline. The pipeline runs all phases and produces a finished video without human intervention. It must work correctly on its own every single time.

## The Flow

```
Scheduler fires (race session ended)
  → Duplicate check: skip if episode already exists for this race + type
  → Create Episode record, enqueue pipeline

PHASE 1 — CONTENT GATHERING & SCRIPT GENERATION
  The most important phase. This is where the episode becomes funny and relevant.

  1a. Load news articles (RSS/HTML) for topical F1 stories
      - News sources configured in DB (news_sources table)
      - Articles scored for relevance to the race/weekend
      - Fed to script generator as news_context

  1b. Load race results from database
      - Actual finishing positions, lap times, incidents
      - Ensures script references real events, not made-up results

  1c. Load character personalities from database
      - 42 characters: 22 drivers, 11 team principals, 9 pundits
      - Each has: comedy angle, satirical take, signature expressions, humor style
      - Physical features (for image prompts), voice descriptions (for TTS)
      - Team affiliations, rivalries, nationality

  1d. Load running gags from database
      - Recurring jokes that build across episodes (e.g., a driver's trademark complaint)
      - Cooldown tracking (don't overuse the same gag)
      - Usage recorded after script generation

  1e. Load storylines from database
      - Multi-episode narrative arcs (rivalries, character arcs, season plots)
      - Beat progression tracked across episodes

  1f. Load team data
      - Team names, livery colours/descriptions (for accurate car colours in images)
      - Driver lineups, team principals

  1g. Script generation (Anthropic Haiku)
      - ALL of the above is fed to the LLM as context
      - Generates ~26 scenes with: dialogue, action, scene_type, face_visible
      - scene_type: TALKING_HEAD, ACTION_REPLAY, ESTABLISHING, TWO_SHOT, OVER_THE_SHOULDER, PODIUM
      - face_visible: true for character scenes, false for action/landscape
      - MUST be funny. Satirical. Topical. Build on gags and storylines.
      - Character dialogue must match their personality and comedy angle

PHASE 2a — IMAGE GENERATION (fal.ai)
  Routes based on face_visible flag from script:

  | face_visible | Image Backend | What Happens |
  |---|---|---|
  | false (ACTION_REPLAY, etc.) | flux-lora | LoRA style, racing direction rules, no character face |
  | true + face ref exists | instant-character | Face ref + LoRA, scale=0.3, 1280x1280→720 crop |
  | true + no face ref | flux-lora fallback | LoRA + detailed prompt description |

  Prompt features:
  - Close-up → MEDIUM SHOT rewriting (prevent head cropping)
  - "Camera 3 meters away" framing guard
  - Racing direction rules (all cars same direction, show rear wings)
  - Episode appearance/clothing consistency
  - Team livery colours from team data

PHASE 2a-bis — End frames for FLF-capable video backends

PHASE 2b — VIDEO GENERATION (fal.ai, configured backend)

PHASE 2c — TTS AUDIO (only if video backend has no native audio)
  - Edge TTS with 42 character voice mappings
  - Voice matches character nationality and speaking style

PHASE 3 — STITCHING (ffmpeg concatenation)

PHASE 4 — YOUTUBE UPLOAD (currently disabled for manual review)
  - Title, description, tags generated from episode content

PHASE 5 — CLEANUP (old assets beyond retention policy)
```

**Each phase commits to DB after completion.** Crash recovery resumes from where it left off.

## Rules

1. **Fix the pipeline, NEVER fix individual scenes.** This system runs automated. A fix to one scene is thrown away on the next scheduled run. Every fix MUST go into the pipeline code. This is the #1 rule. Violating it wastes money and time.

2. **Feature parity between pipeline and jobs.** `video_pipeline.py::_get_scene_image_fal` and `jobs.py::_async_scene_image` must always have the same capabilities. No exceptions.

3. **Never touch scene audio.** Native audio from video backends is sacred. TTS mux destroyed weeks of work previously.

4. **Never regenerate existing episodes.** Scheduler checks for duplicates. API returns 409.

5. **Never state API capabilities as facts without verifying.** Test or check docs first.

6. **Content is king.** The script must be funny, topical, and use all available context (news, gags, storylines, personalities). A technically perfect video that isn't funny is worthless.

## External Services & Costs

| Service | What For | Cost Per Use |
|---------|----------|-------------|
| fal.ai flux-lora | Scene images (action/landscape) | $0.035/image |
| fal.ai instant-character | Scene images (character faces) | $0.04/image |
| fal.ai Ovi | Video clips | $0.20/clip |
| fal.ai Kling 3.0 | Video clips (higher quality) | $0.42-$0.84/clip |
| Anthropic Haiku | Script generation | ~$0.02/episode |
| Edge TTS | Voice generation | Free |
| MinIO | Object storage | Self-hosted |
| YouTube Data API | Video upload | Free (quota limited) |

**Full episode cost estimate:** ~$6-8 with Ovi, ~$15-25 with Kling. Do not waste runs.

## Key Decisions

- **instant-character over flux-general**: flux-general's IP-Adapter bleeds face into background. instant-character preserves identity at scale=0.3.
- **flux-lora for action shots**: No face needed, cheaper, faster. Racing direction rules keep cars pointing correctly.
- **1280x1280 → 720 crop**: Square gen gives headroom, crop to 16:9 preserves head/hair.
- **Close-up rewriting**: instant-character zooms into face. WIDE MEDIUM SHOT + "5m away" + CRITICAL FRAMING prevents extreme close-ups.
- **LTX 2.3 blocked**: ComfyUI integration failed after 20h (2026-03-12). Ovi is active engine.
- **YouTube auto-upload disabled**: Manual review until pipeline quality validated.
- **Team livery descriptions in DB**: Injected into image prompts for correct car colours.

## Database Content (must be populated for quality episodes)

- **Characters** (42): drivers, principals, pundits — each with full personality JSON
- **Teams** (10+): names, livery descriptions, driver lineups
- **Races**: F1 calendar with session times (triggers scheduler)
- **Race Results**: actual finishing data (scraped after each session)
- **News Sources**: RSS/HTML feeds for topical content scraping
- **Running Gags**: recurring jokes with cooldowns and usage tracking
- **Storylines**: multi-episode narrative arcs with beat progression

## Known Issues

- Scene validation (ffmpeg screenshots + Claude Vision) exists as separate job, NOT in pipeline flow yet
- YouTube upload code exists but auto-upload disabled pending quality validation
- RunPod ComfyUI pod still needed for character caricature generation only
