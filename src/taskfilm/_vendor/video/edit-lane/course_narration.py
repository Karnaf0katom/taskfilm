"""Course voice adapter over the existing TTS, chunking and audio-stitch owners."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import course_delivery
import long_narration
import tts_registry


def narrate(text: str, directory: Path, *, key: str, voice: str, language: str) -> dict:
    text = text.strip()
    if not text or len(text) > 100000:
        raise ValueError("Use 1–100000 script characters per lesson")
    if not key or not voice or not language:
        raise ValueError("Supply one voice key, voice id and course language")
    if directory.exists() or directory.is_symlink():
        raise ValueError("Narration directory must be new; previous reads are kept")
    directory.mkdir(parents=True)
    output = directory / "narration.wav"
    try:
        with course_delivery.one_key(key):
            speak = tts_registry.resolve_tts(language, provider="elevenlabs", model="eleven_v3")

            def synth(chunk, filename):
                audio = speak(chunk, lang=language, voice=voice)
                if not audio:
                    raise ValueError("The voice service returned empty audio")
                Path(filename).write_bytes(audio)

            result = long_narration.synthesize_long(text, synth, str(output), max_chars=1500,
                        workdir=str(directory / "chunks"), ext="mp3", gap_ms=100)
        if not course_delivery.probe(output)["audio"]:
            raise ValueError("Narration has no audio stream")
    except Exception:
        # Provider responses and account details must not enter a course report.
        raise ValueError("AI narration failed. Check the supplied key, voice access and allowance; prior reads are kept.") from None
    digest = hashlib.sha256()
    with output.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    receipt = {"audio": str(output), "language": language, "voice_id": voice,
               "model": "eleven_v3", "script_sha256": hashlib.sha256(text.encode()).hexdigest(),
               "audio_sha256": digest.hexdigest(),
               "chunks": result["chunks"], "characters": len(text), "pronunciation_review": "required"}
    (directory / "NARRATION.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt
