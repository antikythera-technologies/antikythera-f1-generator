# Video Generation Pipeline

## Overview

The Antikythera F1 Generator uses **Ovi** (via HuggingFace) to convert static character images into 5-second animated video clips with synchronized speech and sound effects.

## Tested & Validated ✅

**Date:** 2026-01-28
**Status:** Working

## HuggingFace Space

| Space | Endpoint | Status |
|-------|----------|--------|
| `akhaliq/Ovi` | Stateful UI only | ❌ No direct API |
| `alexnasa/Ovi-ZEROGPU` | `/generate_scene` | ✅ **USE THIS** |

## API Integration

### Connection

```python
from gradio_client import Client

client = Client(
    "alexnasa/Ovi-ZEROGPU",
    hf_token="hf_xxxxxxxxxx"  # HuggingFace token
)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `text_prompt` | string | Speech + audio caption with special tokens |
| `sample_steps` | int | Generation quality (30-50 recommended) |
| `image` | filepath | Source character image |

### Special Tokens

#### Speech Tokens `<S>...<E>`
Makes the character speak the enclosed text with lip sync.

```
<S>Simply lovely! Another win for Red Bull!<E>
```

#### Audio Caption Tokens `<AUDCAP>...<ENDAUDCAP>`
Adds ambient sound effects and background audio.

```
<AUDCAP>Crowd cheering loudly, engines revving in background, triumphant celebration atmosphere<ENDAUDCAP>
```

### Full Prompt Example

```
Max Verstappen celebrating victory, pumping his fist in the air. 
He shouts <S>Yes! Simply lovely! Another win!<E>. 
<AUDCAP>Crowd cheering loudly, engines revving in background, triumphant celebration atmosphere<ENDAUDCAP>.
```

### API Call

```python
result = client.predict(
    text_prompt=prompt,
    sample_steps=40,
    image=handle_file('/path/to/character.png'),
    api_name="/generate_scene"
)
# Returns: path to generated video file
```

## Output Specification

| Attribute | Value |
|-----------|-------|
| Duration | 5 seconds |
| Resolution | 576×896 (portrait) |
| Video Codec | H.264 |
| Audio Codec | AAC |
| File Size | ~1.6 MB per clip |

## Pipeline Flow

```
Character Image → Ovi API → 5-sec Clip → MinIO Storage → ffmpeg Stitch
       ↓              ↓            ↓              ↓             ↓
  3D Render      Animate +     H.264/AAC    f1-video-clips   Final 2min
                 Speech +                      bucket          video
                 SFX
```

## Implementation in Backend

### Service Location
`backend/app/services/video_service.py`

### Key Functions

```python
async def generate_clip(
    character_image: str,
    scene_prompt: str,
    speech_text: str,
    audio_atmosphere: str,
    sample_steps: int = 40
) -> str:
    """
    Generate a 5-second video clip from a character image.
    
    Args:
        character_image: Path to character PNG
        scene_prompt: Action description
        speech_text: What the character says (wrapped in <S><E>)
        audio_atmosphere: Background sounds (wrapped in <AUDCAP><ENDAUDCAP>)
        sample_steps: Quality setting (higher = slower but better)
    
    Returns:
        Path to generated MP4 file
    """
    prompt = f"{scene_prompt} <S>{speech_text}<E>. <AUDCAP>{audio_atmosphere}<ENDAUDCAP>."
    
    result = client.predict(
        text_prompt=prompt,
        sample_steps=sample_steps,
        image=handle_file(character_image),
        api_name="/generate_scene"
    )
    return result
```

## Storage

### Development
- Local: `projects/antikythera-f1/clips/`
- Test outputs: `projects/antikythera-f1/assets/`

### Production
- MinIO Bucket: `f1-video-clips`
- Access: `https://minio.antikythera.co.za/f1-video-clips/`

## Quality Settings

| Use Case | sample_steps | Time | Quality |
|----------|--------------|------|---------|
| Quick test | 20 | ~30s | Low |
| Standard | 40 | ~60s | Good |
| Final render | 50 | ~90s | Best |

## Rate Limits

- HuggingFace ZeroGPU spaces have queue limits
- Expect ~1-2 minute wait per clip during peak times
- For 24 clips: budget 30-60 minutes total generation time

## Hybrid Strategy: Real Camera + AI

Clawdbot can capture real video clips from mobile devices:

```
nodes camera_clip --node Ovi --facing front --durationMs 5000
```

Use cases:
- Reaction shots to overlay on AI content
- Style references for generation prompts
- Host/presenter segments
- B-roll transitions

See: [NODE_VIDEO_CLIPS.md](./NODE_VIDEO_CLIPS.md)

## Error Handling

### Common Issues

1. **Queue Timeout** - HuggingFace space is busy
   - Retry with exponential backoff
   - Consider off-peak hours (UTC night)

2. **Invalid Token** - HuggingFace token expired
   - Refresh token in `.env`

3. **Image Format** - Wrong format or size
   - Use PNG, 576×896 or similar portrait ratio

## Environment Variables

```env
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OVI_SPACE=alexnasa/Ovi-ZEROGPU
OVI_SAMPLE_STEPS=40
```

## Test Results

**Test Date:** 2026-01-28
**Input:** `max_verstappen_red_bull_racing.jpg`
**Output:** `ovi-test-output.mp4`
**Status:** ✅ Success

- Speech tokens processed correctly
- Audio atmosphere generated
- Lip sync working
- 5-second duration confirmed
- H.264/AAC encoding confirmed

---

## Next Steps

- [ ] Implement `video_service.py` with retry logic
- [ ] Add progress tracking to database
- [ ] Build batch generation for 24 scenes
- [ ] Integrate with ffmpeg stitching module
