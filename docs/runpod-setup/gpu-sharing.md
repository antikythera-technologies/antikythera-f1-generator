# GPU Sharing Model

**Last Updated**: 2026-03-13

## The Problem

ComfyUI and Ovi share a single RTX A6000 (48 GB VRAM). They **CANNOT run simultaneously** — both load large models that exceed available VRAM when combined.

| Service | Idle VRAM | Inference VRAM | Notes |
|---------|-----------|----------------|-------|
| ComfyUI (Flux loaded) | ~41 GB | ~44 GB | Loads Flux + LoRA + PuLID + CLIP models |
| Ovi (cpu_offload) | ~2.6 GB | ~36 GB | Most weights on CPU, offloaded to GPU during inference |
| Both loaded | **OOM** | **CRASH** | 41 + 36 = 77 GB > 48 GB |

## GPU Sharing Protocol

The pipeline orchestrates GPU access in phases:

### Phase 2a: Image Generation (ComfyUI)

1. Ovi must be **stopped** (not just idle — fully killed)
2. ComfyUI generates all scene images via Flux + LoRA + PuLID
3. Images uploaded to MinIO

### Between Phases

1. Free ComfyUI VRAM: `POST /free {"unload_models": true, "free_memory": true}`
2. This unloads models from VRAM but doesn't kill ComfyUI process

### Phase 2b: Video Generation (Ovi)

1. Start Ovi via GPU manager: `POST /ovi/start`
2. Wait for Ovi Gradio to respond (~90s with cpu_offload)
3. Generate video clips (each clip ~16 min with cpu_offload)
4. Each inference: weights offloaded from CPU → GPU → back to CPU

### After Phase 2b

1. If continuing with more image gen, stop Ovi: `POST /ovi/stop`
2. ComfyUI can reload models on next use

## Start Scripts

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `/workspace/start.sh` | Start both ComfyUI + Ovi | **NOT recommended** — causes VRAM conflict |
| `/workspace/start-comfyui.sh` | Start only ComfyUI | Before image generation |
| `/workspace/start-ovi-now.sh` | Start only Ovi (kills Jupyter first) | Before video generation |
| `/workspace/start-ovi-fast.sh` | Same as ovi-now with cpu_offload | Before video generation |
| `/workspace/start-services.sh` | Start Ollama + Open WebUI | Unrelated to video pipeline |

**CRITICAL**: After pod restart, NO services auto-start. You must manually start the service you need.

## GPU Manager

**File**: `/workspace/gpu_manager.py`
**Port**: 8188 (proxied through ComfyUI's port 19123)
**Note**: Only works when ComfyUI is running (shares the same proxy port)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/ovi/status` | GET | `{"running": bool, "pid": int}` |
| `/ovi/start` | POST | Start Ovi via `start-ovi-now.sh` |
| `/ovi/stop` | POST | Kill Ovi process (SIGTERM + SIGKILL) |
| `/gpu/status` | GET | nvidia-smi memory summary |

**Limitation**: The GPU manager only responds when ComfyUI is serving on port 19123. If ComfyUI is not running, these endpoints return 502.

## Lessons Learned (2026-03-12 Incident)

1. **Never run Ovi while ComfyUI has models loaded** — even after calling `/free`, ComfyUI may not fully release VRAM
2. The `/free` endpoint returns 200 but may not actually unload all models
3. If Ovi returns `None` in <10 seconds, it silently OOM'd
4. After an OOM crash, both services may become unresponsive, requiring pod restart
5. Pod restart changes the SSH port — always check via RunPod API
