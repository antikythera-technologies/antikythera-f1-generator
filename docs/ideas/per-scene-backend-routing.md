# Per-Scene Backend Routing

**Status**: Idea — architecture supports it, not yet implemented as configurable
**Date**: 2026-03-16
**Priority**: Future enhancement

## Concept

The pipeline already routes different scene types to different image backends:
- `TITLE_CARD`, `ESTABLISHING`, `ACTION_REPLAY` → flux-lora (no face reference, cheap)
- Character scenes (`TALKING_HEAD`, `TWO_SHOT`, `PODIUM`, etc.) → instant-character (face ref + LoRA)

This same pattern can be extended to **video generators** — use cheaper/faster backends for simple scenes and premium backends for hero moments.

## Proposed Scene-Type → Backend Mapping

| Scene Type | Image Backend | Video Backend | Est. Cost |
|-----------|--------------|--------------|-----------|
| TITLE_CARD | flux-lora | LTX 2.3 | $0.035 + $0.30 |
| ACTION_REPLAY | flux-lora | Kling 3.0 Pro (better motion) | $0.035 + $0.84 |
| TALKING_HEAD | instant-character | LTX 2.3 | $0.04 + $0.30 |
| TWO_SHOT | instant-character | Kling 3.0 Std | $0.04 + $0.63 |
| OVER_THE_SHOULDER | instant-character | LTX 2.3 | $0.04 + $0.30 |
| PODIUM | instant-character | Kling 3.0 Std | $0.04 + $0.63 |
| ESTABLISHING | flux-lora | LTX 2.3 | $0.035 + $0.30 |
| REACTION | instant-character | LTX 2.3 | $0.04 + $0.30 |

## Cost Impact (26-scene episode)

**Current** (all LTX 2.3): ~$9.50/episode
**Tiered** (premium for 3-5 hero scenes): ~$11-13/episode
**Benefit**: Significantly better motion quality for action/racing scenes

## Implementation

1. Add `scene_type` column to `episode_scenes` table (already in script output, just not stored)
2. Create a `SCENE_TYPE_BACKEND_MAP` config (settings page or DB)
3. Image job reads scene_type → picks image backend
4. Video job reads scene_type → picks video backend
5. Settings page: allow override per scene type

## Why This Works

- instant-character doesn't support Kling/Ovi face references — only relevant for image gen
- Video generators work from the generated image regardless of which image backend made it
- The scene_type is determined at script generation time, so routing is fully automated

## Dependencies

- Need to store `scene_type` from script generator output in the DB
- Need to verify Kling 3.0 produces better action/racing video than LTX 2.3
- Cost analysis needed on a full episode to validate ROI
