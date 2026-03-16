# LTX 2.3 Audit

**Last Updated**: 2026-03-13
**Status**: BLOCKED — not producing valid output after 20+ hours of debugging (2026-03-10 to 2026-03-12)

## Current State

LTX 2.3 via ComfyUI has not successfully generated a single usable video scene. The pipeline code is written and the workflow is defined, but execution fails or produces garbage output.

## Known Issues

### 1. Model Name Mismatch (CRITICAL)

The backend config (`config.py`) references:
```
LTX23_MODEL_NAME = "ltx-2-19b-dev-fp8.safetensors"  # 19B params
```

But the actual model on the server is:
```
/workspace/comfyui/models/checkpoints/ltx-2.3-22b-dev-fp8.safetensors  # 22B params, 28 GB
```

**This mismatch means ComfyUI may be failing to find the model file.** The config needs to be updated to `ltx-2.3-22b-dev-fp8.safetensors`.

### 2. Denoise Strength Confusion

- `denoise=0.30` causes video degradation (frame 0 OK, frame 60+ = static/noise)
- `denoise=1.0` is required for AV mode (audio latent starts empty, needs full denoising)
- `LTXVImgToVideo` handles image guidance via conditioning, NOT via denoise strength
- This distinction was not obvious and caused many failed attempts

### 3. End Frame Flickering

Using both start frame and end frame with `LTXVAddGuide` caused ghosting/flickering artifacts. Solution was to use single start frame only — but this was discovered late.

### 4. VRAM Constraints

LTX 2.3 (22B FP8 = 28 GB) + Gemma 3 (12B FP8 = 13 GB) + Video VAE (2.3 GB) = ~43 GB. This leaves very little headroom on a 48 GB GPU, especially with ComfyUI overhead.

## What Has Been Tested

| Test | Result | Notes |
|------|--------|-------|
| LTX 2.3 text-to-video via ComfyUI | Failed | Various node errors |
| LTX 2.3 image-to-video via ComfyUI | Failed | Output is garbage/static |
| LTX AV (audio+video) via ComfyUI | Failed | Audio latent issues |
| Multiple denoise values (0.3, 0.5, 0.7, 1.0) | All failed | Different failure modes |
| Single start frame (no end frame) | Reduced flickering | But still no usable output |
| Various STG configurations | No improvement | Tried many cfg/scale combos |

## What Has NOT Been Tested

| Test | Why It Matters |
|------|---------------|
| LTX via HuggingFace Space (web UI) | Isolates whether problem is LTX or ComfyUI |
| LTX via direct Python/diffusers | Same — tests LTX without ComfyUI |
| LTX with the correct model name in config | Model mismatch might be the root cause |
| LTX 2.3 official I2V workflow template (unmodified) | We may have introduced bugs in our custom workflow |
| LTX on a GPU with more VRAM (e.g., A100 80GB) | Rules out VRAM pressure issues |

## Audit Plan

### Phase 1: Fix the Obvious

1. **Fix model name mismatch** — update `config.py` to `ltx-2.3-22b-dev-fp8.safetensors`
2. **Test the official workflow** — load `video_ltx2_3_i2v.json` in ComfyUI web UI unmodified
3. **Test with a simple prompt** — "A cat walking" with a photo input

### Phase 2: Isolate the Problem

4. **Test LTX outside ComfyUI** — use HuggingFace Space or direct Python inference
5. **Compare node versions** — verify ComfyUI-LTXVideo nodes match the model version
6. **Check ComfyUI compatibility** — v0.16.4 may have issues with LTX 2.3

### Phase 3: Rebuild if Needed

7. If LTX works outside ComfyUI, rebuild the workflow from the official template
8. If LTX doesn't work at all, evaluate alternatives (different model version, different approach)

## Installed Components for LTX

| Component | Version/File | Size |
|-----------|-------------|------|
| Checkpoint | `ltx-2.3-22b-dev-fp8.safetensors` | 28 GB |
| Text Encoder | `gemma_3_12B_it_fp8_scaled.safetensors` | 13 GB |
| Video VAE | `LTX2_video_vae_bf16.safetensors` | 2.3 GB |
| Audio VAE | `LTX2_audio_vae_bf16.safetensors` | 208 MB |
| Custom Nodes | ComfyUI-LTXVideo (commit `531512f`) | — |
| ComfyUI | v0.16.4 | — |

## Pipeline Code Reference

| File | What it does for LTX |
|------|---------------------|
| `backend/app/services/ltx_video_generator.py` | Builds ComfyUI workflow JSON, submits to API |
| `backend/app/pipeline/video_pipeline.py` | Orchestrates LTX path (`_generate_video_clips_ltx`) |
| `backend/app/config.py` | LTX23_* settings (model name, steps, STG params, etc.) |
| `scripts/experiments/test_ltx_av_scene1.py` | Standalone LTX AV test script |
| `scripts/experiments/test_ltx_scene1.py` | Standalone LTX video-only test |
| `scripts/experiments/test_ltx_lipsync_v7.py` | Lip-sync experiments (v2-v7) |
