# ComfyUI Setup

**Last Updated**: 2026-03-13

## Installation

| Item | Value |
|------|-------|
| Version | v0.16.4 (git commit `a7a6335b`) |
| Location | `/workspace/comfyui` |
| Virtual Env | `/workspace/comfyui/comfy-env` |
| PyTorch | 2.4.1+cu124 |
| Start Command | `python main.py --listen 0.0.0.0 --port 19123` |
| Start Script | `/workspace/start-comfyui.sh` |
| Log | `/workspace/comfyui.log` |
| Size on Disk | 65 GB |

## Custom Nodes

| Node Pack | Git Commit | Purpose | Date Installed |
|-----------|-----------|---------|----------------|
| `ComfyUI-LTXVideo` | `531512f` (PR from 2026-03-06) | LTX 2.x video generation nodes | 2026-03-09 |
| `ComfyUI-Ovi` | `ec54c53` ("some vae tweaks") | Ovi video generation nodes | 2026-03-09 |
| `ComfyUI-PuLID-Flux` | `a80912f` | PuLID face identity preservation for Flux | 2026-03-09 |

### ComfyUI-LTXVideo Node Files

29 Python files providing LTX video generation nodes:

| File | Purpose |
|------|---------|
| `nodes_registry.py` | Dynamic node registration |
| `guide.py` | `LTXVAddGuide` — frame conditioning |
| `stg.py` | `LTXVApplySTG`, `STGGuiderAdvanced` — spatiotemporal guidance |
| `latents.py` | `EmptyLTXVLatentVideo`, `LTXVEmptyLatentAudio` |
| `tiled_vae_decode.py` | `LTXVSpatioTemporalTiledVAEDecode` |
| `easy_samplers.py` | Easy-mode samplers |
| `gemma_encoder.py` | Gemma 3 text encoder loader |
| `iclora.py` | IC-LoRA support |
| `low_vram_loaders.py` | Low-VRAM checkpoint loaders |
| `dynamic_conditioning.py` | Dynamic conditioning |
| `vanish_nodes.py` | Vanish point nodes |
| `sparse_tracks.py` | Sparse tracking |
| `masks.py` | Mask utilities |
| `decoder_noise.py` | VAE decoder noise |
| `prompt_enhancer_nodes.py` | Prompt enhancement |
| `q8_nodes.py` | INT8 quantization nodes |
| `tiled_sampler.py` | Tiled sampling |
| `vae_patcher.py` | VAE patching |
| `embeddings_connector.py` | Embedding connections |

## Patches Applied

### PuLID forward_orig Patch

**File**: `/workspace/comfyui/custom_nodes/ComfyUI-PuLID-Flux/pulidflux.py`

**What**: Modified `forward_orig` function (line 65) to accept `transformer_options` and `attn_mask` parameters.

**Why**: Without this patch, PuLID crashes when used with Flux because the transformer passes extra kwargs that the original function signature doesn't accept.

**Lines changed**:
```python
# Line 65-76: Added parameters
def forward_orig(
    ...
    transformer_options={},
    attn_mask: Tensor = None,
)
```

Also added `attn_mask` input to `ApplyPulidFlux` node (line 245, 259, 275-278).

## Python Packages (Key)

Installed in ComfyUI's Python environment (`comfy-env`):

| Package | Version |
|---------|---------|
| torch | 2.4.1+cu124 |
| torchaudio | 2.4.1+cu124 |
| torchvision | 0.19.1+cu124 |

**Note**: No separate `ltx` or `diffusers` package — LTX runs through ComfyUI's built-in model loading + the ComfyUI-LTXVideo custom nodes.

## Built-in LTX Workflow Templates

Located in `comfy-env/lib/python3.11/site-packages/comfyui_workflow_templates_media_video/templates/`:

| Template | Purpose |
|----------|---------|
| `video_ltx2_3_i2v.json` | LTX 2.3 image-to-video |
| `video_ltx2_3_t2v.json` | LTX 2.3 text-to-video |
| `video_ltx2_i2v.json` | LTX 2.x image-to-video |
| `video_ltx2_i2v_distilled.json` | LTX 2.x distilled I2V |
| `video_ltx2_i2v_lora.json` | LTX 2.x I2V with LoRA |
| `video_ltx2_canny_to_video.json` | LTX 2.x Canny edge → video |
| `video_ltx2_depth_to_video.json` | LTX 2.x depth → video |
| `ltxv_image_to_video.json` | LTX v1 image-to-video (legacy) |
| `ltxv_text_to_video.json` | LTX v1 text-to-video (legacy) |

Also: `/workspace/comfyui/blueprints/Depth to Video (ltx 2.0).json`
