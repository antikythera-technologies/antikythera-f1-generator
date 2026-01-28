#!/usr/bin/env python3
"""
Test script for Nano Banana Pro (Gemini 3 Pro Image) integration.

Tests character consistency by generating multiple images of the same character
with different actions and verifying the style remains consistent.

Usage:
    # Set your API key first
    export GEMINI_API_KEY="your-key-here"
    
    # Run the test
    python test_nano_banana.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))


async def test_single_image():
    """Test generating a single image with character consistency."""
    from app.services.image_generator import ImageGenerator, VISUAL_STYLE_GUIDE, CHARACTER_TEMPLATES
    
    print("=" * 60)
    print("TEST 1: Single Image Generation")
    print("=" * 60)
    
    generator = ImageGenerator()
    
    # Test with Max Verstappen
    result = await generator.generate_scene_image(
        scene_number=1,
        episode_id=0,  # Test episode
        character_name="max_verstappen",
        action_description="Max Verstappen celebrating victory, pumping his fist in the air with excitement",
        resolution="1K",
    )
    
    print(f"✅ Generated: {result.image_path}")
    print(f"   Time: {result.generation_time_ms}ms")
    print(f"   Prompt length: {len(result.prompt_used)} chars")
    
    return result.image_path


async def test_character_consistency():
    """Test that multiple images of the same character maintain consistency."""
    from app.services.image_generator import ImageGenerator
    
    print("\n" + "=" * 60)
    print("TEST 2: Character Consistency (Multiple Poses)")
    print("=" * 60)
    
    generator = ImageGenerator()
    
    actions = [
        "Max Verstappen celebrating victory, raising trophy above head",
        "Max Verstappen looking frustrated in the cockpit after a mechanical failure",
        "Max Verstappen giving a press conference, speaking to journalists",
    ]
    
    results = []
    for i, action in enumerate(actions):
        print(f"\nGenerating pose {i+1}/3: {action[:50]}...")
        result = await generator.generate_scene_image(
            scene_number=i + 1,
            episode_id=0,
            character_name="max_verstappen",
            action_description=action,
            resolution="1K",
        )
        results.append(result)
        print(f"   ✅ {result.image_path} ({result.generation_time_ms}ms)")
    
    print("\n📁 Generated files for consistency review:")
    for r in results:
        print(f"   - {r.image_path}")
    
    return results


async def test_multiple_characters():
    """Test generating different F1 characters."""
    from app.services.image_generator import ImageGenerator
    
    print("\n" + "=" * 60)
    print("TEST 3: Multiple Characters")
    print("=" * 60)
    
    generator = ImageGenerator()
    
    characters = [
        ("max_verstappen", "Standing proudly on the podium"),
        ("lewis_hamilton", "Walking through the paddock looking thoughtful"),
        ("charles_leclerc", "Sitting in the Ferrari cockpit, helmet on"),
        ("lando_norris", "Laughing with team members in the McLaren garage"),
    ]
    
    results = []
    for char_name, action in characters:
        print(f"\nGenerating {char_name}...")
        result = await generator.generate_scene_image(
            scene_number=1,
            episode_id=0,
            character_name=char_name,
            action_description=action,
            resolution="1K",
        )
        results.append((char_name, result))
        print(f"   ✅ {result.image_path}")
    
    return results


async def test_reference_image():
    """Test generating a canonical reference image for a character."""
    from app.services.image_generator import ImageGenerator
    
    print("\n" + "=" * 60)
    print("TEST 4: Reference Image Generation")
    print("=" * 60)
    
    generator = ImageGenerator()
    
    result = await generator.generate_character_reference(
        character_name="max_verstappen",
        pose="neutral portrait, face and upper body visible",
        resolution="2K",
    )
    
    print(f"✅ Reference image: {result.image_path}")
    print(f"   Resolution: 2K")
    print(f"   Time: {result.generation_time_ms}ms")
    
    return result


async def main():
    """Run all tests."""
    # Check for API key
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ Error: GEMINI_API_KEY environment variable not set")
        print("   Set it with: export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)
    
    print("🍌 Nano Banana Pro (Gemini 3 Pro Image) Test Suite")
    print("=" * 60)
    print(f"API Key: {os.environ['GEMINI_API_KEY'][:10]}...")
    print()
    
    try:
        # Run tests
        await test_single_image()
        await test_character_consistency()
        await test_multiple_characters()
        await test_reference_image()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\nGenerated images are in: /tmp/f1-images/")
        print("Review them to verify character consistency!")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
