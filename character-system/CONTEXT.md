# Character System — Layer 2 Context

## What This Workspace Does

Character system for the F1 satirical video series. 32 characters (21 drivers + 11 team principals) with personality definitions, face references, and generated caricatures.

## Personality JSONs

Location: `personalities/{drivers,principals,pundits}/*.json`

Each JSON contains:
- Identity (display_name, team, nationality)
- Personality traits (temperament, humor style)
- Physical features (height, build, hair, distinguishing features)
- Comedy angle + satirical angle + comedy exaggeration
- Signature expression, gestures, poses
- Voice description
- Animation notes

Loaded by `backend/app/services/personality.py` which extracts traits for image generation prompts.

## Face References

- Local: `face-references/` directory (44 files, all 42 active characters covered)
- MinIO: `f1-characters/face-references/{character_name}.{ext}`
- API: GET/POST `/characters/{id}/face-reference`
- Pipeline flow: MinIO -> local temp -> upload to ComfyUI -> use in PuLID workflow
- CRITICAL: Face reference photos MUST be close-up headshots for best PuLID results

## Caricature Generation

- Stack: Flux Dev fp8 + ANTKF1STYLE LoRA (strength 1.4) + PuLID (weight 0.7)
- Trigger word: ANTKF1STYLE
- Resolution: 768x1344 (portrait)
- Stored in MinIO: `f1-characters/{character_id}/caricature.png`
- Batch script: `scripts/generate_all_characters.py` (4 phases: faces, generate, upload, clean)
- DB sync: `scripts/sync_character_db.py` (updates PostgreSQL with MinIO paths)

## Character Grid (2026 Season)

- 22 drivers across 10 teams (some teams have 3 listed for reserves)
- 11 team principals
- Pundits: folder exists but no JSONs yet

## Key Files

- `personalities/drivers/*.json` -- driver personality definitions
- `personalities/principals/*.json` -- team principal personality definitions
- `backend/app/services/personality.py` -- trait loading for prompts
- `backend/app/services/image_generator.py` -- caricature generation via ComfyUI
- `backend/app/models/character.py` -- Character + CharacterImage DB models
- `scripts/generate_all_characters.py` -- batch character generation
- `scripts/sync_character_db.py` -- DB sync after generation
