# Video Generation Backends — Audit & Reference

**Date**: 2026-03-14
**Status**: 8 backends implemented, testing phase

## Architecture

```
Image Generation (always ComfyUI on RunPod)
    → Flux Dev + LoRA (antkf1style_v1) + PuLID (face identity)
    → Produces PNG start frames for each scene

Video Generation (selectable backend)
    → Takes start frame image + prompt → produces 5-second video clip
    → Set via VIDEO_GENERATOR_DEFAULT in .env
```

**Key design**: Images and video generation are fully decoupled. ComfyUI on
RunPod handles all image generation. Video generation is pluggable — switch
backends by changing one env var.

---

## Available Backends

### Self-Hosted (RunPod)

| Backend ID | Engine | Cost/Episode (24 scenes) | Audio | Status |
|------------|--------|--------------------------|-------|--------|
| `ovi` / `runpod-ovi` | Ovi via Gradio on RunPod | ~$5 (GPU hours) | Native | Scene 1 tested, pipeline fragile |
| `ltx` / `runpod-ltx` | LTX 2.3 via ComfyUI on RunPod | ~$5 (GPU hours) | Native | BLOCKED — see audit below |

### fal.ai Hosted API

| Backend ID | Engine | Cost/Video | Cost/Episode (24 scenes) | Audio |
|------------|--------|-----------|--------------------------|-------|
| `fal-ovi` | Ovi | $0.20 | **$4.80** | Native (lip sync) |
| `fal-ltx` | LTX 2.3 (1080p) | $0.30 | **$7.20** | Native |
| `fal-kling-std` | Kling 3.0 Standard | $0.42 | **$10.08** | No (use TTS) |
| `fal-kling-std-audio` | Kling 3.0 Standard | $0.63 | **$15.12** | Native |
| `fal-kling-pro` | Kling 3.0 Pro | $0.42 | **$10.08** | No (use TTS) |
| `fal-kling-pro-audio` | Kling 3.0 Pro | $0.84 | **$20.16** | Native |

### Configuration

```bash
# In .env:
VIDEO_GENERATOR_DEFAULT=fal-ovi    # or any backend ID from tables above
FAL_KEY=your_fal_api_key_here      # Required for fal-* backends
```

---

## LTX 2.3 Audit — Why It's Blocked

**Timeline**: 2026-03-10 to 2026-03-12 (20+ hours)
**Result**: 0 successful scenes from 10 experiments

### Experiments Attempted

| # | Script | Approach | Result |
|---|--------|----------|--------|
| 1 | `test_ltx_scene1.py` | Image-to-video, denoise=0.30 | Failed — frames degrade to static |
| 2 | `test_ltx_av_scene1.py` | AV native audio, denoise=1.0 | Failed — still garbage output |
| 3 | `test_ltx_lipsync.py` | Audio latent conditioning | Failed — no lip sync |
| 4 | `test_ltx_lipsync_v2.py` | v1 + TTS mux replacement | Failed — bad video persists |
| 5 | `test_ltx_lipsync_v3.py` | Audio padding alignment | Failed — padding didn't help |
| 6 | `test_ltx_lipsync_v4.py` | Frame count + format fixes | Failed — MP3→WAV didn't help |
| 7 | `test_ltx_lipsync_v4b_align.py` | DTW + cross-correlation | Failed — post-processing can't fix bad video |
| 8 | `test_ltx_lipsync_v5.py` | Text-based speech in prompt | Failed — no speech from text |
| 9 | `test_ltx_lipsync_v6.py` | Official workflow params | Failed — same issues |
| 10 | `test_ltx_lipsync_v7.py` | Simplified text prompt | Failed — same issues |

### Root Causes Identified

1. **Model name mismatch (CRITICAL)**
   - Config: `ltx-2-19b-dev-fp8.safetensors` (19B params)
   - Actual file on RunPod: `ltx-2.3-22b-dev-fp8.safetensors` (22B params, 28GB)
   - ComfyUI may fail to find the model file

2. **Denoise strength confusion**
   - `denoise=0.30` → frame 0 OK, frames 60+ degrade to noise/static
   - `denoise=1.0` required for AV mode (audio latent starts empty)
   - `LTXVImgToVideo` uses conditioning for image guidance, NOT denoise

3. **Audio conditioning broken**
   - `LTXVAudioVAEEncode` produces garbage
   - Unclear if model issue or ComfyUI node misconfiguration

4. **VRAM pressure**
   - LTX 22B (28GB) + Gemma 3 12B (13GB) + VAEs (~3GB) = ~44GB on 48GB GPU
   - Very little headroom

### What Was NOT Tested

- LTX via HuggingFace Space (isolates ComfyUI as the problem)
- LTX via direct Python/diffusers
- LTX with correct model name in config
- LTX official I2V workflow (completely unmodified)
- LTX on A100 80GB (rules out VRAM pressure)

### Resolution

LTX 2.3 is available on fal.ai (`fal-ltx`) for $0.30/video. This bypasses
all ComfyUI issues. Use `fal-ltx` for testing; revisit RunPod LTX only if
fal.ai quality is insufficient.

---

## RunPod Ovi Audit — Why It's Fragile

### Architecture Problem

One RunPod GPU pod runs BOTH:
- ComfyUI (port 19123) — image generation
- Ovi Gradio server (port 8888) — video generation

The pipeline does a complex GPU-sharing dance:
1. Stop Ovi → free GPU
2. Generate 24 images via ComfyUI
3. Free ComfyUI VRAM → start Ovi
4. Wait for Ovi model load (~2-5 min)
5. Generate 24 videos via Ovi Gradio
6. Each step communicates via custom `/ovi/start`, `/ovi/stop`, `/ovi/status` endpoints

### Failure Points

- Ovi Gradio server fails to start silently
- RunPod proxy URLs can timeout or expire
- GPU OOM if models aren't fully unloaded between switches
- Ovi requires `--cpu_offload` (without it: OOM at 46GB)
- With cpu_offload: ~16 min/clip, ~36 GiB VRAM

### Resolution

Use `fal-ovi` ($0.20/video) for reliable Ovi generation. Keep RunPod for
image generation only. Downsize GPU if images are the only workload.

---

## TTS + Audio Muxing

All backends can use TTS for character-specific voices:
- Edge TTS (Microsoft) — free, high-quality
- Character voice map: david_croft, max_verstappen, etc.
- Audio muxed onto video via ffmpeg (tempo-adjusted to fit scene duration)

For backends with native audio (fal-ovi, fal-ltx, fal-kling-*-audio):
- TTS replaces native audio track when `TTS_ENABLED=true`
- This gives consistent character voices across all backends
- Set `TTS_ENABLED=false` to keep native audio

---

## Testing Checklist

For each backend, test a single scene before running full episode:

```bash
# 1. Set backend in .env
VIDEO_GENERATOR_DEFAULT=fal-ovi

# 2. Set FAL_KEY in .env (for fal-* backends)
FAL_KEY=your_key_here

# 3. Generate a test episode (creates script + images + videos)
curl -X POST http://localhost:8000/api/v1/episodes \
  -H "Content-Type: application/json" \
  -d '{"race_id": 1, "episode_type": "race_preview"}'

# 4. Check scene status
curl http://localhost:8000/api/v1/episodes/1/scenes
```

### Quality Comparison Plan

Generate scene 1 of the same episode with each backend, then compare:
1. Visual quality (motion smoothness, artifact level)
2. Style preservation (does it maintain the caricature art style?)
3. Audio quality (lip sync for Ovi, ambient for others)
4. Generation time
5. Cost

---

## File Locations

| File | Purpose |
|------|---------|
| `backend/app/services/fal_video_generator.py` | fal.ai video generation (all 6 backends) |
| `backend/app/services/ovi_video_generator.py` | RunPod Ovi (self-hosted) |
| `backend/app/services/ltx_video_generator.py` | RunPod LTX 2.3 (self-hosted, BLOCKED) |
| `backend/app/services/ovi_space_manager.py` | RunPod pod lifecycle management |
| `backend/app/pipeline/video_pipeline.py` | Pipeline orchestrator (routes to backends) |
| `backend/app/config.py` | All settings (VIDEO_GENERATOR_DEFAULT, FAL_KEY) |
| `scripts/experiments/test_*.py` | Historical experiments (archived reference) |
