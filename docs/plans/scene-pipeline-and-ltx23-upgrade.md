# Scene Pipeline Overhaul & LTX 2.3 Integration Plan

**Date**: 2026-03-11
**Status**: Planned
**Author**: Wian Koch + Claude

---

## Executive Summary

The current pipeline generates flat character portraits with no scene context, stores no prompts for traceability, and uses an outdated LTX-2 video model that can't handle portrait format. This plan overhauls the entire scene generation pipeline to produce cinematic, director-quality scene imagery with full prompt traceability, and integrates the new LTX 2.3 video model with native first-frame/last-frame support.

**Key change**: Every scene now generates TWO images (start frame + end frame) with full cinematographic direction, giving precise control over the 5-second video clip that LTX 2.3 generates between them.

---

## Architecture Overview

### Current Flow (Broken)
```
Haiku → { character, action, dialogue, audio }
  → Image Generator builds portrait from character traits (no scene context)
  → ONE image per scene (just a character with team-color gradient background)
  → OVI converts image to video (no start/end frame control)
  → Prompts NOT stored in database
```

### New Flow
```
Haiku → { start_frame_prompt, end_frame_prompt, video_prompt, dialogue, audio, camera_direction }
  → Image Generator builds TWO cinematic scene images per scene
  → Both images uploaded to MinIO for traceability
  → LTX 2.3 generates video using start_frame + end_frame + video_prompt
  → ALL prompts stored in database at every stage
  → Any scene can be reviewed, edited, and regenerated individually
```

---

## WORKSTREAM 1: Rich Scene Prompts & Traceability

### Phase 1A — Database Migration

Add columns to `episode_scenes` table:

| Column | Type | Purpose |
|--------|------|---------|
| `start_frame_prompt` | Text | LLM-generated visual description of scene opening |
| `end_frame_prompt` | Text | LLM-generated visual description of scene ending |
| `start_frame_prompt_final` | Text | Enriched prompt actually sent to ComfyUI (with LoRA trigger, character traits, style instructions) |
| `end_frame_prompt_final` | Text | Enriched prompt actually sent to ComfyUI for end frame |
| `start_frame_path` | String(500) | MinIO path to generated start frame image |
| `end_frame_path` | String(500) | MinIO path to generated end frame image |
| `video_prompt` | Text | Motion/camera/transition prompt sent to LTX 2.3 |
| `video_generator` | String(50) | Which engine generated this: "ovi", "ltx23" |
| `camera_direction` | Text | Director's camera instructions (stored separately for clarity) |

Keep existing columns (`ovi_prompt`, `source_image_path`, `video_clip_path`) for backward compatibility. Deprecate over time.

**Migration file**: `backend/migrations/versions/XXX_add_scene_dual_frame_columns.py`

**Model changes**: `backend/app/models/scene.py`

---

### Phase 1B — Script Generator Enhancement

**File**: `backend/app/services/script_generator.py`

#### Updated System Prompt

The system prompt must instruct Haiku to think like a **professional TV director** creating a satirical animated show. Every scene gets full cinematographic direction.

#### New Output Format Per Scene

```json
{
  "scene_number": 1,
  "character": "david_croft",
  "dialogue": "Welcome back to the paddock! What an absolutely INSANE race we just witnessed at Albert Park!",
  "audio_description": "Upbeat studio intro music fading out. Ambient studio hum. Croft's voice is energetic, slightly breathless with excitement.",
  "start_frame_prompt": "WIDE ESTABLISHING SHOT of a sleek, modern F1 broadcast studio. The set is bathed in cool blue and purple studio lighting with subtle lens flares. Three large curved LED screens behind the desk display frozen frames of the race start carnage at Albert Park — cars spinning, gravel flying. DAVID CROFT sits behind a curved glass anchor desk, center frame, leaning back in his chair with his hands clasped on the desk. He wears a sharp dark suit with Sky Sports F1 branding. His expression is composed, professional, about to deliver big news. The Sky Sports F1 logo glows in the bottom-left corner of the frame. Depth of field: desk sharp, background screens slightly soft.",
  "end_frame_prompt": "MEDIUM CLOSE-UP of David Croft at the same broadcast desk, now leaning forward with intensity. His right hand is raised mid-gesture, index finger pointing upward for emphasis. His eyebrows are raised, eyes wide with excitement. The LED screens behind him now show a freeze-frame of Bottas crossing the finish line with arms raised. The lighting has shifted slightly warmer — more amber mixed with the blue, reflecting the excitement. Same desk, same studio, tighter framing. Croft fills the right two-thirds of the frame.",
  "camera_direction": "SLOW PUSH IN from wide establishing shot to medium close-up over 5 seconds. Camera moves steadily on a dolly track, no handheld shake. The movement is deliberate and professional, building anticipation. As the camera pushes in, the background screens subtly transition from the crash footage to the Bottas celebration. Croft's body language shifts from composed to energized as the camera reaches the tighter framing.",
  "video_prompt": "Smooth dolly push-in from wide to medium close-up. David Croft transitions from a composed, hands-clasped pose to leaning forward energetically, raising his right hand to gesture. His mouth moves with enthusiastic speech. The background LED screens crossfade from crash footage to celebration footage. Lighting warms slightly as the energy builds. Professional broadcast camera movement, steady and deliberate."
}
```

#### What Each Field Must Contain

**`start_frame_prompt`** — The opening frame, described like a cinematographer's shot list:
- **Shot type**: Wide, medium, close-up, extreme close-up, over-the-shoulder, two-shot, establishing shot
- **Camera position**: Eye-level, low angle (heroic), high angle (diminishing), Dutch angle (tension)
- **Character position**: Where in frame (rule of thirds), body orientation, pose, hand placement
- **Expression**: Exact facial expression, eye direction, mouth position
- **Clothing**: Specific to the scene (team suit, casual paddock wear, formal press conference attire)
- **Setting/Location**: Specific F1 location (broadcast studio, pit wall, paddock walkway, press conference room, podium, team garage, grid, parc ferme, hospitality suite, simulator room)
- **Background details**: What's visible behind the character — screens, other people, equipment, signage, weather
- **Lighting**: Direction, color temperature, mood (dramatic side-lighting, flat press conference fluorescents, golden hour paddock light, harsh garage strip lights)
- **Depth of field**: What's sharp, what's soft
- **Props**: Microphones, headsets, data screens, trophies, champagne bottles, team radios
- **Mood/atmosphere**: The emotional tone the image must convey

**`end_frame_prompt`** — The closing frame, same level of detail but showing:
- How the character's pose/expression has changed (the "arc" of the 5-second scene)
- How the camera framing has changed (if push-in/pull-out/pan)
- Any background changes (screen content, people entering/leaving, lighting shift)
- Must be **similar enough** to the start frame for smooth LTX 2.3 interpolation (same setting, same character, shifted composition)

**`camera_direction`** — Professional camera movement instructions:
- **Movement type**: Dolly push-in, dolly pull-out, pan left/right, tilt up/down, crane up/down, tracking shot, static locked-off, handheld with subtle shake, Steadicam float, whip pan
- **Movement speed**: Slow creep, steady medium pace, fast dramatic push
- **Movement motivation**: Why the camera moves (following action, revealing information, building tension, matching dialogue emphasis)
- **Transition notes**: How this scene's end connects to the next scene's start (hard cut, match cut, similar framing for continuity)

**`video_prompt`** — What LTX 2.3 needs to animate between the frames:
- Camera movement description (matching camera_direction but in natural language)
- Character motion: specific body movements, gestures, head turns, lip sync notes
- Background motion: screen changes, people moving, light shifts
- Pacing: where in the 5 seconds does the main action happen
- Style preservation note: "Maintain caricature art style throughout, subtle animation only"

**`dialogue`** — Kept short and punchy (max 15 words for 5 seconds):
- Must be deliverable in 5 seconds
- Written with comedic timing in mind (setup-punchline within the scene or across scenes)
- Character voice: matches the personality (Crofty's breathless enthusiasm, Horner's dry sarcasm, Toto's measured intensity)

**`audio_description`** — Full sound design direction:
- **Voice tone**: Whispering conspiratorially, shouting with excitement, dripping with sarcasm, deadpan delivery
- **Background sounds**: Engine revs, crowd noise, radio chatter, press conference camera shutters, rain on garage roof, champagne popping
- **Music**: If any — dramatic sting, comedic "boing", suspenseful drone, triumphant fanfare
- **Sound effects**: Specific moments (door slam, phone buzzing, data screen beep)
- **Silence**: If the comedic beat requires a pause or dead silence for effect

#### Scene Continuity Rules (in System Prompt)

The script generator must also follow these continuity rules:

1. **Scene-to-scene flow**: The `end_frame_prompt` of scene N should be compositionally compatible with the `start_frame_prompt` of scene N+1. If it's the same character continuing, use very similar framing. If it's a different character/location, design a clean visual cut.

2. **Location consistency**: If scenes 1-3 are in the broadcast studio, all three should describe the same studio with consistent details. Don't change the set between cuts to the same location.

3. **Narrative arc**: The 24 scenes should tell a complete story:
   - Scenes 1-3: Cold open / introduction
   - Scenes 4-8: First act — the main race story (what happened, reactions)
   - Scenes 9-14: Second act — deep dive, controversy, drama, heated exchanges
   - Scenes 15-19: Third act — comedy peaks, running gags pay off, hot takes
   - Scenes 20-23: Resolution — final thoughts, predictions, character moments
   - Scene 24: Sign-off / cliffhanger / punchline

4. **Character blocking**: No more than 3-4 unique characters per episode. Each character should appear in 4-8 scenes. This allows consistent visual settings per character and reduces the number of unique environments to generate.

5. **Running gag integration**: If a running gag involves a visual element (e.g., Horner's coffee mug getting progressively larger), the start/end frame prompts must include it with the correct progression state.

#### SceneScript Dataclass Update

```python
@dataclass
class SceneScript:
    scene_number: int
    character: str
    dialogue: Optional[str]
    audio_description: Optional[str]
    start_frame_prompt: str
    end_frame_prompt: str
    camera_direction: str
    video_prompt: str
```

#### Updated System Prompt (Key Additions)

```
You are a professional TV director and satirical comedy writer creating an animated F1 show.

For each scene you must provide FULL cinematographic direction as if briefing
a director of photography. Every visual detail matters — shot type, camera angle,
character position in frame, expression, clothing, setting, lighting, depth of field,
background elements, props, and mood.

You are generating TWO key frames per scene (start and end) and the camera/motion
direction for the 5-second animation between them. Think of it like creating
storyboard panels with detailed director's notes.

CRITICAL: Start and end frames for the same scene must be SIMILAR ENOUGH for smooth
animation (same setting, same character, shifted pose/framing). The video generator
will interpolate between them — if they're too different, you'll get a hard cut
instead of smooth motion.

Shot type vocabulary: WIDE, MEDIUM WIDE, MEDIUM, MEDIUM CLOSE-UP, CLOSE-UP,
EXTREME CLOSE-UP, TWO-SHOT, OVER-THE-SHOULDER, ESTABLISHING SHOT, INSERT SHOT

Camera movement vocabulary: STATIC (locked-off tripod), DOLLY PUSH-IN,
DOLLY PULL-OUT, PAN LEFT/RIGHT, TILT UP/DOWN, CRANE UP/DOWN, TRACKING SHOT,
STEADICAM, HANDHELD (subtle), WHIP PAN, SLOW ZOOM
```

---

### Phase 1C — Image Generator Restructuring

**File**: `backend/app/services/image_generator.py`

#### New Method: `build_scene_frame_prompt()`

This method takes the LLM-generated frame prompt and enriches it with character visual consistency details:

```python
def build_scene_frame_prompt(
    self,
    frame_prompt: str,              # From Haiku (start or end frame)
    character_name: str,
    display_name: str,
    role: str | None = None,
    team: str | None = None,
    nationality: str | None = None,
    physical_features: str | None = None,
    comedy_angle: str | None = None,
) -> str:
    """Combine LLM scene description with character visual traits for consistency."""

    team_slug = (team or "").lower().replace(" ", "_")
    team_style = TEAM_COLORS.get(team_slug, PUNDIT_STYLE)

    parts = [
        "ANTKF1STYLE",
        frame_prompt,  # The full cinematic description from Haiku
    ]

    # Inject character physical consistency
    if physical_features:
        parts.append(f"Character physical traits: {physical_features}")

    # Core caricature style (appended, not overriding scene description)
    parts.append(
        "Satirical caricature style with oversized head, exaggerated facial features, "
        "photorealistic skin with visible pores. Dramatic lighting with deep shadows."
    )

    return " ".join(parts)
```

Key difference from current `build_character_prompt()`:
- The LLM's frame prompt is the **primary** description (setting, camera, composition)
- Character traits are **injected** for visual consistency, not used to build the whole prompt
- No more "head and shoulders portrait crop only" — the scene dictates the framing

#### Updated `generate_scene_image()` Method

```python
async def generate_scene_image(
    self,
    scene_number: int,
    episode_id: int,
    character_name: str,
    frame_prompt: str,              # NEW: from Haiku
    frame_type: str = "start",      # NEW: "start" or "end"
    character_traits: dict | None = None,
    face_image: str | None = None,
) -> GeneratedImage:
```

Now generates from the frame prompt instead of building a portrait.

#### Two Images Per Scene

The pipeline will call `generate_scene_image()` twice per scene:
1. Once with `frame_type="start"` and `frame_prompt=scene.start_frame_prompt`
2. Once with `frame_type="end"` and `frame_prompt=scene.end_frame_prompt`

Output filenames:
- `episode_{id}_scene_{num:02d}_start_{timestamp}.png`
- `episode_{id}_scene_{num:02d}_end_{timestamp}.png`

---

### Phase 1D — Pipeline Integration

**File**: `backend/app/pipeline/video_pipeline.py`

#### Updated Pipeline Phases

**Phase 1 — Script Generation** (unchanged concept, richer output)
```
Haiku generates script → 24 scenes with full cinematographic direction
Store to DB: start_frame_prompt, end_frame_prompt, camera_direction, video_prompt,
             dialogue, audio_description per scene
```

**Phase 2a — Image Generation** (doubled)
```
For each scene (1-24):
  1. Generate START frame image via ComfyUI (Flux + LoRA + PuLID)
  2. Upload start frame to MinIO → save path to scene.start_frame_path
  3. Save scene.start_frame_prompt_final (exact prompt sent to ComfyUI)
  4. Generate END frame image via ComfyUI
  5. Upload end frame to MinIO → save path to scene.end_frame_path
  6. Save scene.end_frame_prompt_final
  7. Commit scene to DB (intermediate save for crash recovery)

Total: 48 images, ~22 minutes at ~27s per image
```

**Phase 2b — Video Generation** (LTX 2.3 with dual frames)
```
For each scene (1-24):
  1. Download start frame and end frame from MinIO (or use local cache)
  2. Upload both to ComfyUI (LTX 2.3 workflow)
  3. Generate 5-second video clip using start_frame + end_frame + video_prompt
  4. Upload video clip to MinIO → save path to scene.video_clip_path
  5. Save scene.video_generator = "ltx23"
  6. Commit scene to DB (intermediate save)

Total: 24 video clips
```

**Phase 3 — Stitching** (unchanged)
```
ffmpeg concatenates 24 clips → final video
```

**Phase 4 — YouTube Upload** (unchanged)

**Phase 5 — Cleanup** (unchanged)

#### MinIO Storage Structure

```
f1-scene-images/
  race_001/
    episode_1/
      scene_01_start.png
      scene_01_end.png
      scene_02_start.png
      scene_02_end.png
      ...
      scene_24_start.png
      scene_24_end.png

f1-video-clips/
  race_001/
    episode_1/
      scene_01.mp4
      scene_02.mp4
      ...
      scene_24.mp4
```

#### Crash Recovery

The pipeline already commits after each scene. With two images per scene, it should commit after EACH image (not just after each scene). If the pipeline crashes after generating scene 12's start frame but before the end frame, it should be able to resume from scene 12's end frame.

Add `start_frame_status` and `end_frame_status` tracking, or simply check for the existence of `start_frame_path` / `end_frame_path` when resuming.

---

### Phase 1E — API Endpoints

**File**: New `backend/app/api/scenes.py` or extend `backend/app/api/episodes.py`

#### Scene Detail Endpoint

```
GET /api/v1/episodes/{episode_id}/scenes/{scene_number}
```

Returns full scene data including all prompts:
```json
{
  "scene_number": 1,
  "character": { "id": 48, "name": "david_croft", "display_name": "David Croft" },
  "status": "completed",
  "dialogue": "Welcome back to the paddock!",
  "audio_description": "Upbeat studio intro music fading out...",
  "start_frame_prompt": "WIDE ESTABLISHING SHOT of a sleek, modern F1 broadcast studio...",
  "end_frame_prompt": "MEDIUM CLOSE-UP of David Croft at the same broadcast desk...",
  "start_frame_prompt_final": "ANTKF1STYLE WIDE ESTABLISHING SHOT of a sleek...",
  "end_frame_prompt_final": "ANTKF1STYLE MEDIUM CLOSE-UP of David Croft...",
  "camera_direction": "SLOW PUSH IN from wide establishing shot to medium close-up...",
  "video_prompt": "Smooth dolly push-in from wide to medium close-up...",
  "start_frame_path": "f1-scene-images/race_001/episode_1/scene_01_start.png",
  "end_frame_path": "f1-scene-images/race_001/episode_1/scene_01_end.png",
  "video_clip_path": "f1-video-clips/race_001/episode_1/scene_01.mp4",
  "video_generator": "ltx23",
  "generation_time_ms": 45230,
  "created_at": "2026-03-11T..."
}
```

#### Update Prompts Endpoint

```
PUT /api/v1/episodes/{episode_id}/scenes/{scene_number}/prompts
```

Body:
```json
{
  "start_frame_prompt": "Updated description...",
  "end_frame_prompt": "Updated description...",
  "camera_direction": "Updated direction...",
  "video_prompt": "Updated motion prompt..."
}
```

Any field omitted is left unchanged. This allows editing just one prompt.

#### Regenerate Endpoints

```
POST /api/v1/episodes/{episode_id}/scenes/{scene_number}/regenerate-start-frame
POST /api/v1/episodes/{episode_id}/scenes/{scene_number}/regenerate-end-frame
POST /api/v1/episodes/{episode_id}/scenes/{scene_number}/regenerate-video
POST /api/v1/episodes/{episode_id}/scenes/{scene_number}/regenerate-all
```

Each uses the stored prompts. `regenerate-all` does: start frame → end frame → video.

---

### Phase 1F — Dashboard Scene Detail View

**Files**: Dashboard components

#### Scene Card Enhancement
- Thumbnail previews of start frame and end frame side by side
- Video clip player
- Status badges (pending, generating, completed, failed)
- Click to expand to full scene detail

#### Scene Detail Modal/Page
- Full display of all prompts (editable textareas)
- Side-by-side preview: start frame | end frame
- Video clip player below
- "Regenerate Start Frame" / "Regenerate End Frame" / "Regenerate Video" buttons
- Generation metadata: time taken, video generator used, retry count
- History of regenerations (if we track versions)

---

## WORKSTREAM 2: LTX 2.3 Installation & Integration

### Phase 2A — Config & Settings

**File**: `backend/app/config.py`

```python
# LTX 2.3 Video Generation (via ComfyUI)
LTX23_ENABLED: bool = False
LTX23_MODEL_NAME: str = ""                          # Set after installation
LTX23_UPSCALER_MODEL: str = ""                      # Set after installation
LTX23_VAE_NAME: str = ""                            # Set after installation
LTX23_TEXT_ENCODER: str = ""                         # Set after installation
LTX23_WIDTH: int = 768
LTX23_HEIGHT: int = 1344                             # Portrait format
LTX23_FRAME_COUNT: int = 121                         # ~5s at 24fps
LTX23_FPS: int = 24
LTX23_STEPS: int = 20
LTX23_DENOISE_STRENGTH: float = 0.40
LTX23_CONDITIONING_SCALE: float = 0.90
LTX23_GUIDANCE_SCALE: float = 3.0
LTX23_SEED: int = -1                                 # -1 = random
LTX23_UPSCALE: bool = False                          # Two-pass upscaler
COMFYUI_TIMEOUT_SECONDS: int = 600
VIDEO_GENERATOR_DEFAULT: str = "ltx23"               # "ovi" | "ltx23"
```

**File**: `.env.example` — add corresponding env vars with comments.

---

### Phase 2B — Shared ComfyUI Client

**New file**: `backend/app/services/comfyui_client.py`

Extract shared ComfyUI HTTP logic used by both image and video generators:

```python
class ComfyUIClient:
    """Shared client for ComfyUI API interactions."""

    async def upload_image(self, local_path: str, filename: str) -> str
    async def queue_prompt(self, workflow: dict) -> str
    async def poll_for_completion(self, prompt_id: str, timeout: int = 600) -> dict
    async def download_file(self, filename: str, subfolder: str, file_type: str) -> bytes
    async def check_health(self) -> bool
```

Both `ImageGenerator` and `LTX23VideoGenerator` use this client instead of duplicating HTTP code.

---

### Phase 2C — LTX 2.3 Video Generator Service

**New file**: `backend/app/services/ltx23_video_generator.py`

```python
class LTX23VideoGenerator:
    """Generate video clips using LTX 2.3 via ComfyUI with first/last frame support."""

    PRESETS = {
        "caricature": {
            "denoise_strength": 0.30,
            "conditioning_scale": 0.95,
            "guidance_scale": 2.0,
            "steps": 18,
        },
        "standard": { ... },
        "high_motion": { ... },
    }

    def _build_workflow(
        self,
        start_frame_filename: str,
        end_frame_filename: str,
        video_prompt: str,
        seed: int,
    ) -> dict:
        """Build ComfyUI workflow for LTX 2.3 image-to-video with first/last frame."""
        # Node types will be determined during RunPod installation (Phase 2D)
        # The workflow uses:
        # 1. Model loader (LTX 2.3 checkpoint)
        # 2. Text encoder
        # 3. Load start frame image
        # 4. Load end frame image
        # 5. First-frame + last-frame conditioning
        # 6. Sampler
        # 7. Decoder
        # 8. (Optional) Spatial upscaler 2x
        # 9. Video output / save
        ...

    async def generate_clip(
        self,
        scene_number: int,
        start_frame_path: str,
        end_frame_path: str,
        video_prompt: str,
        dialogue: str | None = None,
        audio_description: str | None = None,
    ) -> LTX23VideoClip:
        """Generate a 5-second video clip from start and end frame images."""
        # 1. Upload both frames to ComfyUI
        # 2. Build workflow with both frames
        # 3. Queue, poll, download
        # 4. Return video clip
        ...
```

The workflow structure will be finalized after Phase 2D (RunPod installation) when we know the exact LTX 2.3 ComfyUI node names. The service is structured to make this easy to update.

---

### Phase 2D — RunPod Installation

**Target**: Pod `tims42v3eaqrz7` (RTX A6000 48GB, 200GB disk)

#### Steps

1. **Check disk space**: `df -h /workspace`

2. **Update ComfyUI**:
   ```bash
   cd /workspace/comfyui && git pull
   ```

3. **Update/install LTX custom nodes**:
   ```bash
   cd /workspace/comfyui/custom_nodes
   # Update existing LTX nodes
   cd ComfyUI-LTXVideo && git pull
   # Or install fresh if needed
   git clone https://github.com/Lightricks/ComfyUI-LTXVideo
   ```

4. **Download LTX 2.3 models**:
   ```bash
   cd /workspace/comfyui/models
   # Video generator model (~20GB) → checkpoints/
   # Spatial upscaler (~1GB) → checkpoints/ or upscale_models/
   # VAE (1.5GB) → vae/
   # Text encoder (if new) → clip/
   # Audio model → checkpoints/
   ```

   Model download URLs will come from https://ltx.io/model/ltx-2-3 and the ComfyUI-LTXVideo repo.

5. **Test in ComfyUI Web UI**:
   - Access via `https://tims42v3eaqrz7-19123.proxy.runpod.net`
   - Build a minimal workflow: load model → text encode → load start image → load end image → first/last frame conditioning → sample → decode → save video
   - Test with portrait format (768x1344)
   - Confirm video output is not grey/empty
   - Confirm audio generation works

6. **Record exact node names**: Query `/object_info` for all LTX 2.3 node class types. Update `ltx23_video_generator.py` with correct names.

7. **Update startup script**: Ensure `start-comfyui.sh` handles the new models.

#### Disk Space Budget

| Item | Size | Location |
|------|------|----------|
| Existing models (Flux, CLIP, PuLID, LoRA, etc.) | ~20GB | Various |
| LTX-2 models (can be removed after 2.3 validated) | ~8GB | checkpoints/ |
| LTX 2.3 video generator | ~20GB | checkpoints/ |
| LTX 2.3 upscaler | ~1GB | upscale_models/ |
| LTX 2.3 VAE | ~1.5GB | vae/ |
| LTX 2.3 text encoder | ~4GB | clip/ |
| LTX 2.3 audio model | ~13GB | checkpoints/ |
| **Total estimated** | **~67GB** | |
| **Disk capacity** | **200GB** | |
| **Headroom** | **~133GB** | Sufficient |

#### Fallback: Wan2GP

If ComfyUI integration proves problematic (nodes not available, workflow bugs), the fallback is:

- Install Wan2GP alongside ComfyUI on the same pod
- Wan2GP auto-downloads and manages LTX 2.3 models
- Better VRAM management for low-VRAM scenarios (not our concern with 48GB)
- Simpler API but less integration with our existing ComfyUI pipeline
- Would require a separate service class in our backend

ComfyUI is the preferred path since our image generation already uses it.

---

### Phase 2E — Pipeline Integration (Video Generator Selection)

**File**: `backend/app/pipeline/video_pipeline.py`

#### Key Simplification

Since LTX 2.3 runs on ComfyUI (same as image generation), the GPU swap dance is eliminated:

**Before** (OVI):
```
Phase 2a: Stop Ovi → Generate images via ComfyUI → Commit
Phase 2b: Free ComfyUI VRAM → Start Ovi → Generate videos via Ovi → Commit
```

**After** (LTX 2.3):
```
Phase 2a: Generate 48 images via ComfyUI (Flux + LoRA + PuLID) → Commit
Phase 2b: Free VRAM → Generate 24 videos via ComfyUI (LTX 2.3) → Commit
```

No more starting/stopping Ovi. No more RunPod GPU management endpoints. Both phases run through ComfyUI with a VRAM free between model swaps.

#### Video Generator Factory

```python
def _create_video_generator(self) -> VideoGeneratorProtocol:
    if settings.VIDEO_GENERATOR_DEFAULT == "ltx23":
        from app.services.ltx23_video_generator import LTX23VideoGenerator
        return LTX23VideoGenerator(quality="caricature")
    else:
        # Fallback to OVI
        from app.services.ovi_space_manager import RunPodManager
        return RunPodManager(quality="caricature")
```

---

### Phase 2F — A/B Comparison (Follow-up)

**New endpoint**: `POST /api/v1/episodes/{episode_id}/scenes/{scene_number}/compare`

Generates the same scene with both OVI and LTX 2.3 for quality comparison:
- Uses the stored start/end frame images
- Generates two videos
- Stores both in MinIO with engine suffix: `scene_01_ovi.mp4`, `scene_01_ltx23.mp4`
- Returns both paths for side-by-side viewing in dashboard

---

### Phase 2G — GPU Simplification (Future)

If LTX 2.3 quality is confirmed superior to OVI:
- Remove OVI from the pipeline entirely
- Remove `OviSpaceManager` / `RunPodManager` from video generation path
- Remove GPU management custom node (`/ovi/start`, `/ovi/stop`)
- Simplify `docker-compose` (remove Ovi-related services)
- Single ComfyUI process handles everything

---

## Implementation Sequencing

### Dependency Graph

```
Phase 1A (DB migration) ──────> Phase 1B (Script generator)
                                       │
                                       v
                                Phase 1C (Image generator)
                                       │
                                       v
                                Phase 1D (Pipeline integration)
                                       │
Phase 1E (API endpoints) ─────────────┘
       │
       v
Phase 1F (Dashboard)


Phase 2A (Config) ──────> Phase 2B (ComfyUI client) ──> Phase 2C (LTX23 service)
                                                                    │
Phase 2D (RunPod install) ─────────────────────────────────────────┘
       │                                                            │
       v                                                            v
Phase 2E (Pipeline integration) ──────> Phase 2F (A/B compare) ──> Phase 2G (Simplify)
```

### Sprint Plan

| Sprint | Phases | Deliverable | Effort |
|--------|--------|-------------|--------|
| 1 | 1A, 1B, 1C, 1D | Rich prompts with dual frames, stored in DB, pipeline saves them | 2-3 days |
| 2 | 1E, 1F, 2A, 2B, 2C | API + dashboard for prompt editing, LTX23 service code ready | 2-3 days |
| 3 | 2D, 2E | LTX 2.3 installed on RunPod, working end-to-end in pipeline | 1-2 days |
| 4 | 2F, 2G | A/B comparison, OVI removal if LTX23 proven | 1-2 days |

---

## Risk Considerations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LTX 2.3 ComfyUI nodes not available yet | Can't do Phase 2D | Fall back to Wan2GP; keep OVI as default |
| Haiku image prompts inconsistent quality | Bad scene images | Iterate on system prompt; few-shot examples; allow manual editing |
| 48 images too slow (22 min) | Pipeline takes too long | Parallelize image gen if ComfyUI supports batching; reduce to 24 scenes |
| LTX 2.3 first/last frame does hard cuts | Poor video quality | Ensure start/end frames are similar; tune conditioning strength |
| Disk space insufficient on RunPod | Can't install all models | Delete old LTX-2 models after 2.3 validated; upgrade disk if needed |
| PuLID face consistency in scene context | Characters look different | Keep PuLID weight high; test with various scene compositions |
| LTX 2.3 VRAM conflicts with Flux | OOM errors | Sequential model loading with VRAM free between; ComfyUI handles this |
| Migration breaks existing episodes | Data loss | Migration only adds nullable columns; fully backward compatible |

---

## Testing Approach

### Unit Tests (no external services)
- `SceneScript` dataclass parses all new fields
- `build_scene_frame_prompt()` correctly combines LLM prompt with character traits
- Migration up/down works
- Schema validation for new API fields

### Integration Tests (with DB)
- Pipeline saves all prompt fields to scene
- Pipeline generates two images per scene
- API returns full scene detail with all prompts
- API allows updating individual prompts
- Regeneration endpoints trigger correct generation

### Manual/E2E Tests (requires RunPod)
- Full episode generation with new script format
- Verify scene images show settings/backgrounds (not just portraits)
- Verify LTX 2.3 video quality with first/last frame
- Test single scene regeneration from dashboard
- Compare OVI vs LTX 2.3 quality side-by-side

---

## Summary of File Changes

### New Files
- `backend/app/services/comfyui_client.py` — Shared ComfyUI API client
- `backend/app/services/ltx23_video_generator.py` — LTX 2.3 video generation service
- `backend/migrations/versions/XXX_add_scene_dual_frame_columns.py` — DB migration

### Modified Files
- `backend/app/models/scene.py` — Add 8+ new columns
- `backend/app/schemas/scene.py` — Add new fields to response schemas
- `backend/app/services/script_generator.py` — Rich scene prompts with dual frames
- `backend/app/services/image_generator.py` — New `build_scene_frame_prompt()`, updated `generate_scene_image()`
- `backend/app/pipeline/video_pipeline.py` — Dual frame generation, LTX 2.3 integration, prompt storage
- `backend/app/config.py` — LTX 2.3 settings
- `backend/app/api/episodes.py` — Scene detail and regeneration endpoints
- `dashboard/src/lib/api.ts` — New scene API methods and types
- `dashboard/src/components/episodes/` — Scene detail view components
