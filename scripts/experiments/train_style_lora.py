#!/usr/bin/env python3
"""
Train a Flux LoRA on the F1 caricature style using fal.ai.

Uses the official fal-client SDK for proper large file upload handling.

Trigger word: ANTKF1STYLE
Training set: 30 original Manus.ai F1 caricatures
Cost: ~$2 per run

Usage:
    export FAL_KEY="your-key"
    python train_style_lora.py
"""

import json
import os
import sys

import fal_client

TRAINING_ZIP = "/tmp/f1_caricature_training.zip"
TRIGGER_WORD = "ANTKF1STYLE"


def on_queue_update(update):
    """Handle queue status updates."""
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(f"  [LOG] {log['message']}")
    elif isinstance(update, fal_client.Queued):
        print(f"  In queue (position: {update.position})...")


def main():
    fal_key = os.environ.get("FAL_KEY", "")
    if not fal_key:
        print("ERROR: FAL_KEY not set")
        sys.exit(1)

    print("=" * 60)
    print(f"F1 CARICATURE STYLE LORA TRAINING")
    print(f"Trigger word: {TRIGGER_WORD}")
    print(f"Training images: 30 (Manus.ai originals)")
    print(f"Estimated cost: ~$2")
    print("=" * 60)

    # 1. Upload the ZIP file using fal_client (handles large files)
    print(f"\nUploading training data ({os.path.getsize(TRAINING_ZIP) / 1024 / 1024:.1f} MB)...")
    images_url = fal_client.upload_file(TRAINING_ZIP)
    print(f"  Uploaded: {images_url}")

    # 2. Submit and wait for training
    print(f"\nStarting training (this takes ~10-15 minutes)...")
    print(f"  trigger_word: {TRIGGER_WORD}")
    print(f"  is_style: True")
    print(f"  steps: 1000")
    print()

    result = fal_client.subscribe(
        "fal-ai/flux-lora-fast-training",
        arguments={
            "images_data_url": images_url,
            "trigger_word": TRIGGER_WORD,
            "is_style": True,
            "create_masks": False,
            "steps": 1000,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    # 3. Print results
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)

    lora_file = result.get("diffusers_lora_file", {})
    config_file = result.get("config_file", {})

    print(f"  LoRA weights URL: {lora_file.get('url', 'N/A')}")
    print(f"  LoRA size:        {lora_file.get('file_size', 0) / 1024 / 1024:.1f} MB")
    print(f"  Config URL:       {config_file.get('url', 'N/A')}")

    # Save result
    result_path = "test-output/lora_training_result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Full result:      {result_path}")

    print(f"\nTrigger word: '{TRIGGER_WORD}'")
    print(f"Use this LoRA URL with PuLID + LoRA inference to generate new characters.")


if __name__ == "__main__":
    main()
