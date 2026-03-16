# Models, LoRAs, and Assets

**Last Updated**: 2026-03-13

All models are stored under `/workspace/comfyui/models/`.

## Checkpoints

| File | Size | Purpose | Date |
|------|------|---------|------|
| `ltx-2.3-22b-dev-fp8.safetensors` | 28 GB | LTX 2.3 video generation (22B params, FP8 quantized) | 2026-03-12 |
| `LTX2_audio_vae_bf16.safetensors` | symlink → vae/ | Audio VAE for LTX AV mode | — |

**CRITICAL**: Config file (`backend/app/config.py`) references `ltx-2-19b-dev-fp8.safetensors` (19B) but the actual model on server is `ltx-2.3-22b-dev-fp8.safetensors` (22B). This name mismatch needs to be resolved. See [ltx-audit.md](ltx-audit.md).

## UNet Models

| File | Size | Purpose | Date |
|------|------|---------|------|
| `flux1-dev-fp8.safetensors` | 12 GB | Flux Dev FP8 — base model for image generation | 2026-03-09 |

## Text Encoders

| File | Size | Purpose | Date |
|------|------|---------|------|
| `gemma_3_12B_it_fp8_scaled.safetensors` | 13 GB | Gemma 3 12B for LTX 2.3 text encoding | 2026-03-10 |

## CLIP Models

| File | Size | Purpose | Date |
|------|------|---------|------|
| `clip_l.safetensors` | 235 MB | CLIP-L for Flux text encoding | 2026-03-09 |
| `t5xxl_fp8_e4m3fn.safetensors` | 4.6 GB | T5-XXL FP8 for Flux text encoding | 2026-03-09 |
| `EVA02_CLIP_L_336_psz14_s6B.pt` | 817 MB | EVA-CLIP for PuLID face analysis | 2026-03-09 |

## VAE Models

| File | Size | Purpose | Date |
|------|------|---------|------|
| `ae.safetensors` | 320 MB | Flux autoencoder (image gen) | 2026-03-09 |
| `LTX2_video_vae_bf16.safetensors` | 2.3 GB | LTX 2 video VAE (BF16) | 2026-03-10 |
| `LTX2_audio_vae_bf16.safetensors` | 208 MB | LTX 2 audio VAE (BF16) for AV mode | 2026-03-10 |

## LoRAs

| File | Size | Purpose | Strength | Date |
|------|------|---------|----------|------|
| `antkf1style_v1.safetensors` | 86 MB | ANTKF1STYLE — custom F1 caricature art style | 1.4 | 2026-03-09 |

**Backups**:
- MinIO: `f1-characters/lora/antkf1style_v1.safetensors`
- fal.ai CDN: `https://v3b.fal.media/files/b/0a918355/tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors`

## PuLID Models

| File | Size | Purpose | Date |
|------|------|---------|------|
| `pulid_flux_v0.9.0.safetensors` | 1.1 GB | PuLID Flux face identity model | 2026-03-09 |

## InsightFace Models

Located at `/workspace/comfyui/models/insightface/models/antelopev2/`:

| File | Purpose |
|------|---------|
| `genderage.onnx` | Gender/age detection |
| `2d106det.onnx` | 2D face landmark detection (106 points) |
| `1k3d68.onnx` | 3D face landmark (68 points) |
| `glintr100.onnx` | Face recognition (ArcFace) |
| `scrfd_10g_bnkps.onnx` | Face detection (SCRFD) |

## Face References

**Location**: `/workspace/comfyui/input/`
**Count**: 53 face reference images (JPG/PNG/WebP)
**Source**: MinIO bucket `f1-characters/face-references/`

These are synced from MinIO before image generation. Each file is named `{character_name}.{ext}`.

## Model Directory Summary

| Directory | Files | Notes |
|-----------|-------|-------|
| `checkpoints/` | 2 | LTX 2.3 checkpoint + audio VAE symlink |
| `unet/` | 1 | Flux Dev FP8 |
| `text_encoders/` | 1 | Gemma 3 12B |
| `clip/` | 3 | CLIP-L, T5-XXL, EVA-CLIP |
| `vae/` | 3 | Flux AE, LTX video VAE, LTX audio VAE |
| `loras/` | 1 | ANTKF1STYLE |
| `pulid/` | 1 | PuLID Flux v0.9.0 |
| `insightface/` | 5 | AntelopeV2 face analysis |
| `upscale_models/` | 0 | Empty |
| `controlnet/` | 0 | Empty |
