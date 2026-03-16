"""LTX lip-sync v4b: Align TTS audio to LTX video using cross-correlation.

The v4 raw output has correct lip sync (mouth matches LTX audio),
but LTX audio is garbled. We need to align the clean TTS to match
the timing of LTX's audio.

Approach:
  1. Extract LTX audio from raw video
  2. Extract amplitude envelopes from both LTX audio and TTS audio
  3. Cross-correlate envelopes to find the global time offset
  4. Apply the offset when muxing TTS onto LTX video
  5. Also try DTW (Dynamic Time Warping) for non-linear alignment
     in case pacing differs, not just offset

Outputs three versions for comparison:
  - _aligned_xcorr.mp4  — global offset via cross-correlation
  - _aligned_dtw.mp4    — non-linear time-warped TTS via DTW
  - _raw.mp4            — original (already on desktop from v4)
"""

import asyncio
import json
import logging
import shutil
import subprocess
import struct
import tempfile
from pathlib import Path

import numpy as np
from scipy import signal as scipy_signal
from scipy.spatial.distance import cdist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_VIDEO = REPO_ROOT / "test-output/scene-videos/scene_01_lipsync_v4_raw.mp4"
TTS_AUDIO = Path("/tmp/f1-lipsync-v4/ep0_scene_01_dialogue.mp3")
OUTPUT_DIR = REPO_ROOT / "test-output/scene-videos"


def extract_audio_pcm(media_path: str, sample_rate: int = 16000) -> np.ndarray:
    """Extract audio as mono float32 PCM using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", media_path,
        "-ar", str(sample_rate),
        "-ac", "1",
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode()[-300:]}")

    # Parse raw float32 samples
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    return samples


def compute_envelope(audio: np.ndarray, sr: int, hop_ms: int = 10) -> np.ndarray:
    """Compute amplitude envelope with smoothing.

    Returns a downsampled envelope at ~100Hz (10ms hops).
    This captures speech energy patterns while being robust
    to the garbled nature of LTX audio.
    """
    # Rectify
    rectified = np.abs(audio)

    # Smooth with a window (20ms window → captures syllable-level energy)
    window_size = int(sr * 0.020)
    if window_size < 1:
        window_size = 1
    kernel = np.ones(window_size) / window_size
    smoothed = np.convolve(rectified, kernel, mode="same")

    # Downsample to hop_ms resolution
    hop_samples = int(sr * hop_ms / 1000)
    envelope = smoothed[::hop_samples]

    # Normalize to [0, 1]
    peak = np.max(envelope)
    if peak > 0:
        envelope = envelope / peak

    return envelope


def find_offset_xcorr(
    ltx_audio: np.ndarray,
    tts_audio: np.ndarray,
    sr: int,
    hop_ms: int = 10,
) -> float:
    """Find global time offset using cross-correlation of amplitude envelopes.

    Returns offset in seconds: positive = TTS should be delayed,
    negative = TTS should start earlier.
    """
    env_ltx = compute_envelope(ltx_audio, sr, hop_ms)
    env_tts = compute_envelope(tts_audio, sr, hop_ms)

    log.info(f"Envelope lengths: LTX={len(env_ltx)}, TTS={len(env_tts)}")

    # Cross-correlate (full mode gives all possible offsets)
    correlation = scipy_signal.correlate(env_ltx, env_tts, mode="full")

    # The lag axis: negative lags mean TTS leads, positive means TTS follows
    lags = scipy_signal.correlation_lags(len(env_ltx), len(env_tts), mode="full")

    # Find the lag with maximum correlation
    best_idx = np.argmax(correlation)
    best_lag = lags[best_idx]

    # Convert lag from envelope samples to seconds
    offset_seconds = best_lag * hop_ms / 1000.0

    # Confidence: ratio of peak to mean correlation
    mean_corr = np.mean(np.abs(correlation))
    peak_corr = correlation[best_idx]
    confidence = peak_corr / mean_corr if mean_corr > 0 else 0

    log.info(
        f"Cross-correlation: best_lag={best_lag} samples "
        f"({offset_seconds:+.3f}s), confidence={confidence:.1f}x"
    )

    return offset_seconds


def dtw_align(
    ltx_audio: np.ndarray,
    tts_audio: np.ndarray,
    sr: int,
    hop_ms: int = 20,
) -> np.ndarray:
    """Non-linear alignment using Dynamic Time Warping on envelopes.

    Returns a time-warped version of TTS audio that matches LTX timing.
    Uses envelope-based DTW for robustness against garbled audio.
    """
    env_ltx = compute_envelope(ltx_audio, sr, hop_ms)
    env_tts = compute_envelope(tts_audio, sr, hop_ms)

    log.info(f"DTW envelopes: LTX={len(env_ltx)}, TTS={len(env_tts)}")

    # Compute cost matrix (Euclidean distance between envelope values)
    cost = cdist(
        env_ltx.reshape(-1, 1),
        env_tts.reshape(-1, 1),
        metric="euclidean",
    )

    # DTW with Sakoe-Chiba band constraint to prevent extreme warping
    # Band width = 20% of sequence length
    band_width = max(int(0.2 * max(len(env_ltx), len(env_tts))), 10)

    n, m = cost.shape
    dtw_matrix = np.full((n + 1, m + 1), np.inf)
    dtw_matrix[0, 0] = 0

    for i in range(1, n + 1):
        j_start = max(1, i - band_width)
        j_end = min(m + 1, i + band_width + 1)
        for j in range(j_start, j_end):
            dtw_matrix[i, j] = cost[i - 1, j - 1] + min(
                dtw_matrix[i - 1, j],      # insertion
                dtw_matrix[i, j - 1],      # deletion
                dtw_matrix[i - 1, j - 1],  # match
            )

    # Backtrack to find warping path
    path = []
    i, j = n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        candidates = [
            (dtw_matrix[i - 1, j - 1], i - 1, j - 1),
            (dtw_matrix[i - 1, j], i - 1, j),
            (dtw_matrix[i, j - 1], i, j - 1),
        ]
        _, i, j = min(candidates, key=lambda x: x[0])
    path.reverse()

    dtw_cost = dtw_matrix[n, m] / len(path)
    log.info(f"DTW: path_length={len(path)}, avg_cost={dtw_cost:.4f}")

    # Build time mapping: for each LTX envelope frame, which TTS envelope frame?
    # path is list of (ltx_idx, tts_idx) pairs
    hop_samples = int(sr * hop_ms / 1000)

    # Create output at LTX audio length
    ltx_len = len(ltx_audio)
    output = np.zeros(ltx_len, dtype=np.float32)

    for ltx_env_idx, tts_env_idx in path:
        # Map envelope indices back to sample ranges
        ltx_start = ltx_env_idx * hop_samples
        ltx_end = min((ltx_env_idx + 1) * hop_samples, ltx_len)

        tts_start = tts_env_idx * hop_samples
        tts_end = min((tts_env_idx + 1) * hop_samples, len(tts_audio))

        if ltx_end <= ltx_start or tts_end <= tts_start:
            continue

        # Resample TTS chunk to fit LTX chunk size
        tts_chunk = tts_audio[tts_start:tts_end]
        ltx_chunk_len = ltx_end - ltx_start

        if len(tts_chunk) == ltx_chunk_len:
            output[ltx_start:ltx_end] = tts_chunk
        else:
            # Linear interpolation to match lengths
            indices = np.linspace(0, len(tts_chunk) - 1, ltx_chunk_len)
            output[ltx_start:ltx_end] = np.interp(indices, np.arange(len(tts_chunk)), tts_chunk)

    return output


def save_pcm_as_wav(samples: np.ndarray, sr: int, path: str):
    """Save float32 numpy array as WAV file."""
    # Normalize to prevent clipping
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.95

    # Convert to 16-bit PCM
    pcm16 = (samples * 32767).astype(np.int16)

    # Write WAV header + data
    with open(path, "wb") as f:
        num_samples = len(pcm16)
        data_size = num_samples * 2  # 16-bit = 2 bytes per sample
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))          # chunk size
        f.write(struct.pack("<H", 1))           # PCM format
        f.write(struct.pack("<H", 1))           # mono
        f.write(struct.pack("<I", sr))          # sample rate
        f.write(struct.pack("<I", sr * 2))      # byte rate
        f.write(struct.pack("<H", 2))           # block align
        f.write(struct.pack("<H", 16))          # bits per sample
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm16.tobytes())


def mux_with_offset(video_path: str, audio_path: str, output_path: str, offset: float):
    """Mux audio onto video with a time offset.

    offset > 0: delay audio (add silence before speech)
    offset < 0: trim start of audio
    """
    if offset >= 0:
        # Delay audio by inserting silence
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            f"[1:a]adelay={int(offset * 1000)}|{int(offset * 1000)},aresample=44100,aformat=channel_layouts=stereo[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-ac", "2", "-ar", "44100",
            "-shortest",
            output_path,
        ]
    else:
        # Trim start of audio
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", f"{abs(offset):.3f}",
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-ac", "2", "-ar", "44100",
            "-shortest",
            output_path,
        ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Mux failed: {proc.stderr[-300:]}")


def mux_warped_audio(video_path: str, warped_wav: str, output_path: str):
    """Mux DTW-warped audio onto video (no offset needed — already aligned)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", warped_wav,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-ac", "2", "-ar", "44100",
        "-shortest",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Mux failed: {proc.stderr[-300:]}")


def probe_file(path: str, label: str):
    """Print media info."""
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", path],
        capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    dur = float(data["format"]["duration"])
    log.info(f"{label}: {dur:.2f}s")
    for s in data["streams"]:
        ct = s["codec_type"]
        if ct == "video":
            log.info(f"  Video: {s['codec_name']} {s['width']}x{s['height']}")
        elif ct == "audio":
            log.info(f"  Audio: {s['codec_name']} {s['sample_rate']}Hz {s['channels']}ch")


def main():
    log.info("=== LTX Lip-Sync v4b: Audio Alignment ===")

    if not RAW_VIDEO.exists():
        log.error(f"Raw video not found: {RAW_VIDEO}")
        log.error("Run test_ltx_lipsync_v4.py first!")
        return
    if not TTS_AUDIO.exists():
        log.error(f"TTS audio not found: {TTS_AUDIO}")
        return

    SR = 16000  # 16kHz for envelope analysis (plenty for speech energy)

    # Step 1: Extract audio from both sources
    log.info("Step 1: Extracting audio...")
    ltx_pcm = extract_audio_pcm(str(RAW_VIDEO), SR)
    tts_pcm = extract_audio_pcm(str(TTS_AUDIO), SR)
    log.info(f"LTX audio: {len(ltx_pcm)} samples ({len(ltx_pcm)/SR:.2f}s)")
    log.info(f"TTS audio: {len(tts_pcm)} samples ({len(tts_pcm)/SR:.2f}s)")

    # Step 2: Cross-correlation for global offset
    log.info("Step 2: Cross-correlation alignment...")
    offset = find_offset_xcorr(ltx_pcm, tts_pcm, SR)

    xcorr_path = str(OUTPUT_DIR / "scene_01_lipsync_v4_aligned_xcorr.mp4")
    log.info(f"Muxing with offset {offset:+.3f}s...")
    mux_with_offset(str(RAW_VIDEO), str(TTS_AUDIO), xcorr_path, offset)
    probe_file(xcorr_path, "Cross-correlation aligned")

    # Step 3: DTW for non-linear alignment
    log.info("Step 3: DTW non-linear alignment...")
    warped_tts = dtw_align(ltx_pcm, tts_pcm, SR)

    # Save warped audio as WAV
    warped_wav_path = "/tmp/f1-lipsync-v4/tts_dtw_warped.wav"
    save_pcm_as_wav(warped_tts, SR, warped_wav_path)
    log.info(f"DTW-warped audio saved: {warped_wav_path}")

    # Upsample warped audio to 44.1kHz for muxing (16kHz sounds thin)
    warped_hq_path = "/tmp/f1-lipsync-v4/tts_dtw_warped_hq.wav"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", warped_wav_path,
        "-ar", "44100", "-ac", "1",
        warped_hq_path,
    ], capture_output=True)

    dtw_path = str(OUTPUT_DIR / "scene_01_lipsync_v4_aligned_dtw.mp4")
    mux_warped_audio(str(RAW_VIDEO), warped_hq_path, dtw_path)
    probe_file(dtw_path, "DTW aligned")

    # Step 4: Also create a version with the DTW-warped audio at original quality
    # by using the 48kHz TTS WAV as source for DTW
    log.info("Step 4: High-quality DTW alignment (48kHz)...")
    SR_HQ = 48000
    ltx_hq = extract_audio_pcm(str(RAW_VIDEO), SR_HQ)
    tts_hq = extract_audio_pcm(str(TTS_AUDIO), SR_HQ)
    warped_hq = dtw_align(ltx_hq, tts_hq, SR_HQ, hop_ms=20)

    warped_hq48_path = "/tmp/f1-lipsync-v4/tts_dtw_warped_48k.wav"
    save_pcm_as_wav(warped_hq, SR_HQ, warped_hq48_path)

    dtw_hq_path = str(OUTPUT_DIR / "scene_01_lipsync_v4_aligned_dtw_hq.mp4")
    mux_warped_audio(str(RAW_VIDEO), warped_hq48_path, dtw_hq_path)
    probe_file(dtw_hq_path, "DTW aligned (48kHz)")

    # Step 5: Copy all versions to desktop
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        for src, name in [
            (xcorr_path, "scene_01_v4_xcorr.mp4"),
            (dtw_hq_path, "scene_01_v4_dtw.mp4"),
        ]:
            if Path(src).exists():
                dest = desktop / name
                shutil.copy2(src, str(dest))
                log.info(f"Desktop: {dest}")

    log.info("=== DONE ===")
    log.info("Compare on desktop:")
    log.info("  scene_01_lipsync_v4_raw.mp4   — LTX video + LTX garbled audio (baseline)")
    log.info("  scene_01_v4_xcorr.mp4         — LTX video + TTS shifted by cross-correlation")
    log.info("  scene_01_v4_dtw.mp4           — LTX video + TTS warped by DTW (best quality)")
    log.info("")
    log.info(f"Cross-correlation offset: {offset:+.3f}s")


if __name__ == "__main__":
    main()
