# Ovi Setup

**Last Updated**: 2026-03-13

## Installation

| Item | Value |
|------|-------|
| Location | `/workspace/ovi-server` |
| Git Commit | `5b69b25` ("Update README.md") |
| Virtual Env | `/workspace/ovi-server/ovi-env` |
| Python | 3.11.10 |
| PyTorch | 2.6.0+cu124 |
| Gradio | 6.9.0 |
| Start Script | `/workspace/start-ovi-now.sh` |
| Log | `/workspace/ovi-gradio.log` |
| Size on Disk | 65 GB |

## Start Command

```bash
cd /workspace/ovi-server
source ovi-env/bin/activate
python3 gradio_app.py --cpu_offload --server_name 0.0.0.0 --server_port 8888
```

**`--cpu_offload` is REQUIRED** — without it, Ovi OOMs on A6000 48GB:
- With cpu_offload: ~2.6 GB VRAM at idle, ~36 GB during inference, ~16 min/clip
- Without cpu_offload: ~46 GB VRAM, OOM at `F.gelu` in `fusion.py`

## Checkpoints

Located at `/workspace/ovi-server/ckpts/`:

### Ovi Core Model

| File | Size | Purpose |
|------|------|---------|
| `Ovi/model_960x960_10s.safetensors` | 22 GB | Ovi main model (960x960, 10s generation) |
| `Ovi/model_960x960.safetensors` | 22 GB | Ovi main model (960x960, 5s generation) |

### Wan2.2 (Text-Image-to-Video backbone)

| File | Size | Purpose |
|------|------|---------|
| `Wan2.2-TI2V-5B/Wan2.2_VAE.pth` | 2.7 GB | Wan 2.2 VAE |
| `Wan2.2-TI2V-5B/models_t5_umt5-xxl-enc-bf16.pth` | 11 GB | UMT5-XXL text encoder (BF16) |

### MMAudio (Audio generation)

| File | Size | Purpose |
|------|------|---------|
| `MMAudio/ext_weights/best_netG.pt` | 429 MB | Audio generator |
| `MMAudio/ext_weights/v1-16.pth` | 655 MB | Audio model v1-16 |

## Default Config

File: `/workspace/ovi-server/ovi/configs/inference/inference_fusion.yaml`

```yaml
ckpt_dir: ./ckpts
output_dir: ./outputs
sample_steps: 50          # Default steps (overridden by pipeline to 20)
solver_name: unipc
model_name: "960x960_10s"
shift: 5.0
audio_guidance_scale: 3.0
video_guidance_scale: 4.0
mode: "i2v"               # Image-to-video mode
cpu_offload: True
seed: 103
video_negative_prompt: "jitter, bad hands, blur, distortion"
audio_negative_prompt: "robotic, muffled, echo, distorted"
video_frame_height_width: [960, 960]
slg_layer: 11
```

**Note**: The pipeline overrides several of these via Gradio API parameters (steps=20, resolution=992x512, etc.)

## Python Packages (Key)

| Package | Version |
|---------|---------|
| torch | 2.6.0+cu124 |
| torchaudio | 2.6.0+cu124 |
| torchvision | 0.21.0+cu124 |
| diffusers | 0.37.0 |
| transformers | 4.51.3 |
| gradio | 6.9.0 |
| gradio_client | 2.3.0 |
| accelerate | 1.13.0 |
| safetensors | 0.7.0 |
| open_clip_torch | 3.3.0 |

## Gradio API

Endpoint: `/generate_video`

Parameters accepted (from Gradio API info):
- `text_prompt` (str) — video prompt with special tokens
- `image` (file) — first frame image
- `video_frame_height` (int) — default 960
- `video_frame_width` (int) — default 960
- `video_seed` (int)
- `solver_name` (str) — "unipc", "euler", "dpm++"
- `sample_steps` (int)
- `shift` (float)
- `video_guidance_scale` (float)
- `audio_guidance_scale` (float)
- `slg_layer` (int)
- `video_negative_prompt` (str)
- `audio_negative_prompt` (str)

Special tokens for prompts:
- `<S>dialogue text<E>` — speech/dialogue
- `<AUDCAP>audio description<ENDAUDCAP>` — ambient audio
