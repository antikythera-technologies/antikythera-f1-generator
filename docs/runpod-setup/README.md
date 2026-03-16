# RunPod GPU Server Setup

Complete inventory of the Antikythera F1 Generator GPU server.

**Pod ID**: `tims42v3eaqrz7`
**Pod Name**: `antikythera-technologies-gpu`
**Last Audited**: 2026-03-13

## Files

| File | Contents |
|------|----------|
| [server-inventory.md](server-inventory.md) | Hardware, OS, drivers, disk usage |
| [comfyui-setup.md](comfyui-setup.md) | ComfyUI installation, custom nodes, Python packages |
| [models-and-loras.md](models-and-loras.md) | Every model, LoRA, VAE, and face reference on the server |
| [ovi-setup.md](ovi-setup.md) | Ovi installation, checkpoints, Python packages |
| [gpu-sharing.md](gpu-sharing.md) | How ComfyUI and Ovi share the GPU, start scripts, GPU manager |
| [ltx-audit.md](ltx-audit.md) | LTX 2.3 status, known issues, troubleshooting plan |

## Rules

1. **Update this documentation whenever anything is installed, removed, or changed on the server.**
2. Every model file must list: filename, size, purpose, date installed.
3. Every custom node must list: name, git commit, purpose.
4. Every patch must list: file patched, what was changed, why.
