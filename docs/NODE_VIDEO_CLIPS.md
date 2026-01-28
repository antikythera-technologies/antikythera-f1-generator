# Node Video Clips - Real Camera Capture for F1 Content

## Overview

Clawdbot can capture real video clips from paired mobile devices (nodes) using the `camera_clip` action. This enables capturing real-world footage that can be:
- Used as reference material for AI-generated scenes
- Incorporated directly into videos as "behind the scenes" or reaction shots
- Used to create authentic transitions or B-roll
- Captured spontaneously when inspiration strikes

## How It Works

### Prerequisites
1. **Paired Node** - A mobile device (phone/tablet) running the Clawdbot companion app
2. **Camera Access** - App must have camera permissions
3. **Node Online** - Device must be connected to the gateway

### Capture Command

Via Clawdbot nodes tool:
```
nodes camera_clip --node <node-name> --facing <front|back> --durationMs <milliseconds>
```

### Parameters

| Parameter | Description | Options |
|-----------|-------------|---------|
| `node` | Target device name or ID | e.g., "Ovi", "phone" |
| `facing` | Which camera to use | `front` or `back` |
| `durationMs` | Clip length in milliseconds | e.g., 5000 (5 seconds) |
| `maxWidth` | Max video width (optional) | e.g., 1920 |
| `fps` | Frames per second (optional) | e.g., 30 |

### Example Workflow

1. **Quick 5-second clip from Ovi (front camera):**
   ```
   nodes camera_clip --node Ovi --facing front --durationMs 5000
   ```

2. **Higher quality capture:**
   ```
   nodes camera_clip --node Ovi --facing back --durationMs 10000 --maxWidth 1920 --fps 30
   ```

3. **Output** - Returns a media path that can be:
   - Sent directly to chat
   - Saved to the `f1-video-clips` bucket
   - Processed through ffmpeg for editing

## Use Cases for F1 Content

### 1. Reaction Shots
Capture authentic reactions to race moments that can be overlaid on AI-generated content.

### 2. Real-World References
Film real objects, gestures, or movements to inform AI image/video generation prompts.

### 3. Host Segments
Record short "presenter" clips to bookend AI-generated episodes.

### 4. B-Roll
Capture ambient footage (screens, equipment, coffee cups) for transitions.

### 5. Prototype Testing
Quickly capture what a scene should look like before generating the AI version.

## Integration with Ovi Space

The captured clips can be:
1. **Analyzed** - Extract key frames to understand composition
2. **Referenced** - Use as style reference for Ovi generations
3. **Combined** - Stitch real footage with AI-generated clips via ffmpeg

## Storage

Clips are automatically saved and can be organized into:
- **R2 Bucket:** `f1-video-clips` (production assets)
- **Local:** `projects/antikythera-f1/clips/` (development)

## Tips

- **Lighting matters** - Even for AI reference, good lighting helps
- **Steady shots** - Use a stand if possible; phone shake is noticeable
- **5-10 seconds** - Short clips are more versatile than long ones
- **Both cameras** - Front for reactions, back for object/scene capture
- **Label clearly** - Save with descriptive names for easy retrieval

## Related

- [Ovi Space](https://huggingface.co/spaces/akhaliq/Ovi) - AI video generation
- [FFmpeg Integration](../scripts/) - Video processing
- Character Style Guide - For consistent AI generations
