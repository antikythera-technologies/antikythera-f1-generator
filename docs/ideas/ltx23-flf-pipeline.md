# LTX 2.3 First-Last Frame (FLF) Pipeline

**Source:** YouTube — "You're Using LTX 2.3 WRONG! (First & Last Frame Magic)"
**NotebookLM:** Notebook "LTX 2.3" (5e6bc76d), source 244e553b
**Date:** 2026-03-17

## Core Concept

Generate video clips by providing a **start frame** and **end frame** image, then letting LTX 2.3 interpolate all motion between them. This produces seamless, continuous-looking video where scene transitions flow naturally.

## Key Learnings from Video

### Treat LTX 2.3 Like a 5-Year-Old
- Overcomplicated prompts → model gives up → static zoom
- Keep motion descriptions simple and logical
- Don't mix audio + image input simultaneously — model gets overloaded
- Generate video from **image + text prompt only**, add audio in post

### First & Last Frame Rules
- The two images do **90% of the work** — the prompt just bridges them
- Images MUST be logically connected and visually similar
- Simple transitions work (standing → sitting). Complex pose changes fail.
- "Baby logic" — if you can't explain the A→B transition to a child, LTX can't do it
- `source_video_strength` ~0.9 is fine, doesn't vary much between 0.8-0.92

### Production Workflow
- **Test at 480p first** (~1 min/clip) to validate frame connection + motion
- Only bump to 1080p once motion looks right (~6 min/clip)
- The creator made **200+ generations** for a 1-minute polished video
- Cherry-picking is normal and expected for quality output

### Audio Gotcha
- Audio-driven mode kills motion quality — model prioritizes lip sync over movement
- Text-prompt-only mode yields far better motion
- Voice consistency across clips is an unsolved problem in LTX 2.3 native audio
- Our approach (TTS in post) is actually better for this reason

## How This Applies to F1 Generator

### Scene-Level FLF
- Scene N's **end frame** becomes Scene N+1's **start frame**
- Creates seamless flow between scenes instead of hard cuts
- Perfect for: TALKING_HEAD → REACTION transitions, establishing → character transitions

### Per-Scene Pipeline Selection
- Not all scenes benefit from FLF — ACTION_REPLAY and TITLE_CARD are fine with current approach
- Architecture should allow **mixing pipelines per scene**:
  - Scene 1 (TITLE_CARD): flux-lora image → Ovi video (current)
  - Scene 2 (TALKING_HEAD): FLF with start+end frame → LTX 2.3
  - Scene 3 (ACTION_REPLAY): flux-lora image → Kling 3.0 Pro (future)
  - Scene 4 (REACTION): instant-character → Ovi (current)

### What We Already Have
- Script generator already produces `start_frame_prompt` AND `end_frame_prompt`
- We stopped generating end frames to save time — FLF pipeline would re-enable this
- fal.ai has LTX 2.3 with FLF support (no ComfyUI needed)
- Multiple video backend infrastructure already exists

### What We'd Need to Build
1. **FLF video backend** — new service class calling fal.ai LTX 2.3 FLF endpoint
2. **End frame image generation** — re-enable for scenes using FLF pipeline
3. **Frame chaining logic** — scene N end_frame feeds into scene N+1 start_frame
4. **480p preview mode** — test pass before committing to full resolution
5. **Pipeline selector** — per-scene backend selection (some scenes Ovi, some FLF, some Kling)

### Prompt Strategy for FLF
- Video prompt must describe the MOTION connecting frame A to frame B
- Keep it simple: "Camera slowly pushes in as character turns head left"
- NOT: "Dramatic dolly push-in with volumetric fog swirling around character who turns head 45 degrees left while background screens flicker with race telemetry"

## fal.ai LTX 2.3 FLF API

Endpoint: `fal-ai/ltx-2.3` (check for FLF-specific endpoint)
Key parameters to research:
- `first_frame_image` / `last_frame_image`
- `source_video_strength` (~0.9)
- Resolution options (480p preview, 1080p final)
- Audio generation toggle (disable for our use case)

## Next Steps

1. Research fal.ai LTX 2.3 FLF API parameters
2. Build proof-of-concept: take 2 existing scene images, generate FLF clip
3. Compare quality vs current Ovi pipeline
4. If promising, architect the selectable pipeline system
5. Implement frame chaining for seamless episode flow
