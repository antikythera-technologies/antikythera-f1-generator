# Pipeline Workspace Context

> Layer 2 context -- read this when working on scene generation, video generation, or the pipeline itself.

## What This Workspace Does

The video generation pipeline -- 5 sequential phases that turn a race event into a 2-minute satirical F1 video. Each episode generates 24 x 5-second scenes.

## Pipeline Phases

1. **Script Generation** -- Anthropic Haiku generates 24 scene scripts (dialogue, action, audio descriptions) given race context and character personalities.
2. **Video Clip Generation** -- Two sub-phases, two engine options (LTX or Ovi):
   - Phase 2a: Generate scene images via ComfyUI (Flux Dev fp8 + ANTKF1STYLE LoRA + PuLID).
   - Phase 2b: Generate videos from images (LTX via ComfyUI, or Ovi via Gradio).
3. **Stitching** -- ffmpeg concatenates 24 clips into final video (libx264, CRF 23, aac audio).
4. **YouTube Upload** -- OAuth2 resumable upload with metadata (title, description, tags).
5. **Cleanup** -- Delete MinIO assets older than 3 races.

## Video Generators

Selected by `VIDEO_GENERATOR_DEFAULT` in `config.py` (currently `"ltx"`).

| Engine | File | Class | Output | Status |
|--------|------|-------|--------|--------|
| LTX | `../services/ltx_video_generator.py` | `LTXVideoGenerator` | .webm | Code complete, not yet tested in production |
| Ovi | `../services/ovi_video_generator.py` | `OviVideoGenerator` | .mp4 | Working, being phased out |

## GPU Sharing Model

ComfyUI and Ovi share 1x RTX A6000 48GB on RunPod pod `tims42v3eaqrz7`. They CANNOT run simultaneously.

- **Phase 2a**: ComfyUI generates images (Ovi stopped).
- **Between phases**: Free ComfyUI VRAM via `POST /api/free`.
- **Phase 2b (LTX)**: Same ComfyUI instance runs the LTX workflow.
- **Phase 2b (Ovi)**: Start Ovi via GPU manager, generate videos via Gradio.
- **GPU manager endpoints** (on ComfyUI port 19123): `/ovi/start`, `/ovi/stop`, `/ovi/status`, `/gpu/memory`.

## RunPod Access

- Pod ID: `tims42v3eaqrz7`, GPU: RTX A6000 48GB
- ComfyUI: port 19123 (proxy: `https://tims42v3eaqrz7-19123.proxy.runpod.net`)
- Ovi: port 8888 (proxy: `https://tims42v3eaqrz7-8888.proxy.runpod.net`)
- Startup: `bash /workspace/start-comfyui.sh` (NOT auto-started after pod restart)
- Ovi MUST use `--cpu_offload` (without it, OOMs at inference)

## Image Generation Settings

- Model: Flux Dev fp8 + ANTKF1STYLE LoRA (strength 1.4) + PuLID (weight 0.7)
- Trigger word: `ANTKF1STYLE`
- Resolution: 768x1344 (portrait/characters), 1344x768 (landscape/scenes)
- Steps: 20, sampler: euler/simple, CFG: 1.0
- Face references: stored in MinIO `f1-characters/face-references/`, synced to ComfyUI before generation
- CLIP text encode MUST use DualCLIPLoader output directly (NOT LoRA-modified clip)

## LTX 2.3 Workflow (17 nodes)

```
CheckpointLoaderSimple -> CLIPTextEncode (pos/neg) -> LTXVConditioning -> EmptyLTXVLatentVideo
  -> LTXVAddGuide (start frame, idx=0) -> LTXVAddGuide (end frame, idx=-1)
  -> LTXVApplySTG -> STGGuiderAdvanced -> LTXVScheduler -> KSamplerSelect
  -> RandomNoise -> SamplerCustomAdvanced -> LTXVSpatioTemporalTiledVAEDecode -> SaveWEBM
```

Node names that DO NOT exist (from old broken code -- never use these):
`LTXVLoader`, `LTXVTextEncode`, `LTXVSampler`, `LTXVDecode`, `VHS_VideoCombine`

## Key Files

| File | Purpose |
|------|---------|
| `video_pipeline.py` | Orchestrator -- runs all 5 phases |
| `../services/image_generator.py` | ComfyUI image gen (Flux + LoRA + PuLID) |
| `../services/comfyui_client.py` | Shared HTTP client for ComfyUI API |
| `../services/ltx_video_generator.py` | LTX 2.3 video engine |
| `../services/ovi_video_generator.py` | Ovi video engine (legacy) |
| `../services/ovi_space_manager.py` | HuggingFace space lifecycle for Ovi |
| `../services/script_generator.py` | Anthropic Haiku script generation |
| `../services/stitcher.py` | ffmpeg concatenation |
| `../services/storage.py` | MinIO object storage |
| `../services/personality.py` | Character personality trait loader |
| `../config.py` | All settings (`VIDEO_GENERATOR_DEFAULT`, `LTX23_*`, `OVI_*`, `COMFYUI_*`) |

## Intermediate Commits

Pipeline commits to DB after Phase 2a (all images) and after each video clip in Phase 2b. This means:
- If the process crashes during video gen, images are preserved.
- Resume picks up where it left off (skips completed scenes).

## MinIO Storage Paths

```
f1-scene-images/race_{id:03d}/episode_{id}/scene_{num:02d}_{suffix}.png
f1-video-clips/race_{id:03d}/episode_{id}/scene_{num:02d}.{mp4|webm}
f1-final-videos/race_{id:03d}/episode_{id}/final.mp4
```

## Current Development State

Manually testing scene generation one scene at a time:
1. Generate scene -> review -> iterate on prompts/params
2. Continue through all scenes
3. Once satisfied, run full pipeline end-to-end
4. Then automate with scheduler

Image generation: tested and working.
LTX video generation: coded and workflow verified, NOT yet run.
Ovi video generation: tested previously, being phased out.
