#!/usr/bin/env python3
"""
Test Ovi video generation directly.
This creates a simple 5-second test video using Ovi (HuggingFace Gradio).
"""

import time
import sys
import os
from pathlib import Path

try:
    from gradio_client import Client
except ImportError:
    print("Installing gradio_client...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gradio_client", "-q"])
    from gradio_client import Client


def test_ovi_generation():
    """Test Ovi video generation with a sample image."""
    
    print("=" * 60)
    print("ANTIKYTHERA F1 VIDEO GENERATOR - OVI TEST")
    print("=" * 60)
    
    # Use a sample F1 image
    test_image = "https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/F1.svg/1200px-F1.svg.png"
    
    # Build prompt with Ovi special tokens
    action = "Racing car zooms past dramatically"
    dialogue = "And the championship leader crosses the line!"
    audio = "Engine roaring, crowd cheering, excited commentator voice"
    
    prompt = f"{action} <S>{dialogue}<E> <AUDCAP>{audio}<ENDAUDCAP>"
    
    print(f"\n📸 Test image: {test_image}")
    print(f"📝 Prompt: {prompt}")
    print("\n⏳ Connecting to Ovi...")
    
    try:
        client = Client("akhaliq/Ovi")
        print("✅ Connected to Ovi HuggingFace Space")
        
        print("\n📋 Checking available API endpoints...")
        # The API uses /lambda endpoint
        
        print("\n🎬 Generating video clip (this may take a few minutes)...")
        start_time = time.time()
        
        # Call Ovi API with the correct endpoint
        result = client.predict(
            api_name="/lambda",
        )
        
        elapsed = time.time() - start_time
        print(f"\n⏱️ API call completed in {elapsed:.1f}s")
        print(f"📄 Result type: {type(result)}")
        print(f"📄 Result: {result}")
        
        # The result should be a tuple with (image_info, text_prompt, video_info)
        if result and len(result) >= 3:
            video_info = result[2]
            if isinstance(video_info, dict) and 'video' in video_info:
                video_path = video_info['video']
                print(f"📁 Video path: {video_path}")
                
                if Path(video_path).exists():
                    size = Path(video_path).stat().st_size / 1024
                    print(f"📊 File size: {size:.1f} KB")
                    print("\n🎉 SUCCESS! Video generated!")
                    return video_path
        
        print("⚠️ No video in response - the API may have changed")
        return None
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("\nThis could be due to:")
        print("  - Ovi space is currently busy/in queue")
        print("  - The space requires authentication")
        print("  - API structure has changed")
        return None


def check_alternative_spaces():
    """Check other video generation spaces."""
    print("\n" + "=" * 60)
    print("CHECKING ALTERNATIVE VIDEO GENERATION SPACES")
    print("=" * 60)
    
    alternatives = [
        ("ByteDance/AnimateDiff-Lightning", "AnimateDiff Lightning"),
        ("Lightricks/LTX-Video", "LTX Video"),
    ]
    
    for space, name in alternatives:
        print(f"\n🔍 Checking {name}...")
        try:
            client = Client(space)
            print(f"   ✅ Space {name} is accessible")
            print(f"   API: {space}")
        except Exception as e:
            print(f"   ❌ {name} not available: {e}")


if __name__ == "__main__":
    result = test_ovi_generation()
    
    if not result:
        check_alternative_spaces()
    
    sys.exit(0 if result else 1)
