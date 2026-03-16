# Server Inventory

**Last Updated**: 2026-03-13

## Hardware

| Item | Value |
|------|-------|
| Provider | RunPod |
| Pod ID | `tims42v3eaqrz7` |
| Pod Name | `antikythera-technologies-gpu` |
| GPU | NVIDIA RTX A6000 |
| VRAM | 48 GB (49140 MiB) |
| CUDA Compute Capability | 8.6 |
| Cost | $0.33/hr |

## Software

| Item | Version |
|------|---------|
| OS | Ubuntu 22.04.5 LTS |
| Kernel | 6.5.0-35-generic |
| NVIDIA Driver | 550.54.15 |
| Python (system) | 3.11.10 |
| pip (system) | 24.2 |

## Disk

| Path | Size | Contents |
|------|------|----------|
| `/workspace` | 200 GB total, 129 GB used, 72 GB free | All server data |
| `/workspace/comfyui` | 65 GB | ComfyUI + models |
| `/workspace/ovi-server` | 65 GB | Ovi + checkpoints |

## Network Ports

| Port | Service | Proxy URL |
|------|---------|-----------|
| 19123 | ComfyUI | `https://tims42v3eaqrz7-19123.proxy.runpod.net` |
| 8888 | Ovi Gradio | `https://tims42v3eaqrz7-8888.proxy.runpod.net` |
| 22 | SSH | `ssh -p <dynamic> root@135.84.176.142` (port changes on restart) |

**Note**: SSH public port changes every time the pod restarts. Get current port from RunPod API or console.
