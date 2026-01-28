#!/usr/bin/env python3
"""
Test script for Ovi video generation.

Usage:
    # With image path
    python scripts/test_ovi.py --image /path/to/image.jpg
    
    # With character and auto-generate image
    python scripts/test_ovi.py --character max_verstappen
    
    # Specific quality level
    python scripts/test_ovi.py --image /path/to/image.jpg --quality high
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.video_generator import VideoGenerator


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def test_video_generation(
    image_path: str,
    action: str,
    dialogue: str | None = None,
    audio_desc: str | None = None,
    quality: str = "standard",
    output_dir: str = "/tmp/f1-test-videos",
):
    """Test video generation with Ovi."""
    print(f"\n{'='*60}")
    print("OVI VIDEO GENERATION TEST")
    print(f"{'='*60}")
    print(f"Image:       {image_path}")
    print(f"Quality:     {quality}")
    print(f"Action:      {action}")
    print(f"Dialogue:    {dialogue or '(none)'}")
    print(f"Audio:       {audio_desc or '(none)'}")
    print(f"{'='*60}\n")
    
    # Initialize generator
    generator = VideoGenerator(quality=quality)
    
    # Generate
    print("Generating video...")
    clip = await generator.generate_clip(
        scene_number=1,
        image_path=image_path,
        action=action,
        dialogue=dialogue,
        audio_description=audio_desc,
    )
    
    # Copy to output directory
    os.makedirs(output_dir, exist_ok=True)
    import shutil
    from datetime import datetime
    
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_name = f"test_ovi_{timestamp}.mp4"
    output_path = Path(output_dir) / output_name
    
    shutil.copy(clip.video_path, output_path)
    
    print(f"\n{'='*60}")
    print("TEST COMPLETE")
    print(f"{'='*60}")
    print(f"Generation time:  {clip.generation_time_ms}ms")
    print(f"Original path:    {clip.video_path}")
    print(f"Saved to:         {output_path}")
    print(f"{'='*60}\n")
    
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Test Ovi video generation")
    parser.add_argument("--image", "-i", required=True, help="Path to input image")
    parser.add_argument("--action", "-a", default="Character speaking passionately to camera", help="Action description")
    parser.add_argument("--dialogue", "-d", help="Dialogue to synthesize (uses <S>...<E> tokens)")
    parser.add_argument("--audio", help="Background audio description (uses <AUDCAP>...<ENDAUDCAP> tokens)")
    parser.add_argument("--quality", "-q", default="standard", choices=["draft", "standard", "high", "ultra"])
    parser.add_argument("--output", "-o", default="/tmp/f1-test-videos", help="Output directory")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}")
        sys.exit(1)
    
    asyncio.run(test_video_generation(
        image_path=args.image,
        action=args.action,
        dialogue=args.dialogue,
        audio_desc=args.audio,
        quality=args.quality,
        output_dir=args.output,
    ))


if __name__ == "__main__":
    main()
