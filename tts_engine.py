# tts_engine.py
"""
Text-to-Speech engine for the Financial Squawk Box.
Uses edge-tts (Microsoft Neural TTS) for high-quality, zero-latency audio generation.
"""

import os
import uuid
import asyncio
import logging

logger = logging.getLogger("squawkbox.tts")

# ─── Configuration ──────────────────────────────────────────────
VOICE = "en-US-GuyNeural"         # Professional male — authoritative financial news voice
RATE = "+15%"                       # Slightly faster for urgency
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "audio")

os.makedirs(AUDIO_DIR, exist_ok=True)

# ─── Cleanup old audio files (keep last 200) ────────────────────
def cleanup_audio(keep=200):
    """Remove oldest audio files to prevent disk bloat."""
    try:
        files = sorted(
            [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) if f.endswith('.mp3')],
            key=os.path.getmtime
        )
        for f in files[:-keep] if len(files) > keep else []:
            os.remove(f)
    except Exception:
        pass

# ─── TTS Synthesis ──────────────────────────────────────────────
async def synthesize_headline(text: str) -> str:
    """
    Generate TTS audio for a headline.
    Returns the filename (not full path) of the generated MP3.
    """
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed. Run: pip install edge-tts")
        raise

    # Clean text for speech
    clean = text.replace('|', ', ').replace('  ', ' ').strip()
    if not clean:
        raise ValueError("Empty text for TTS")

    filename = f"{uuid.uuid4().hex[:10]}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    try:
        communicate = edge_tts.Communicate(clean, VOICE, rate=RATE)
        await communicate.save(filepath)
        logger.debug(f"TTS generated: {filename} ({len(clean)} chars)")

        # Periodic cleanup
        cleanup_audio()

        return filename
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        # Clean up partial file
        if os.path.exists(filepath):
            os.remove(filepath)
        raise
