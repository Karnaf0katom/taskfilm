"Split long scripts into sentence chunks and stitch their generated reads."

from __future__ import annotations

import os

import re

import tempfile

from typing import Callable, Sequence

import audio_stitch  # edit-lane sibling — REUSE its trim+normalize+join, don't re-implement

DEFAULT_MAX_CHARS = 300  # Chatterbox /generate_tts_audio hard cap (~300 chars); keep chunks under it

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")

_CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+")

def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Split ONE over-long sentence into <=max_chars pieces on clause boundaries, then words, never
    mid-word (a single monster token is hard-cut as a last resort)."""
    pieces: list[str] = []
    cur = ""
    for part in _CLAUSE_SPLIT.split(sentence):
        part = part.strip()
        if not part:
            continue
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars  # a single unbroken token longer than the cap — hard cut
            pieces.append(part[:cut].strip())
            part = part[cut:].strip()
        if not cur:
            cur = part
        elif len(cur) + 1 + len(part) <= max_chars:
            cur = f"{cur} {part}"
        else:
            pieces.append(cur)
            cur = part
    if cur:
        pieces.append(cur)
    return [p for p in pieces if p]

def chunk_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split ``text`` into <=``max_chars`` chunks on sentence boundaries (packing consecutive sentences
    up to the cap), falling back to clause/word splitting for a single over-long sentence. Deterministic;
    whitespace-collapsed; never cuts mid-word. Empty/whitespace text -> ``[]``."""
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    text = " ".join((text or "").split())
    if not text:
        return []
    chunks: list[str] = []
    cur = ""
    for sentence in (s for s in _SENT_SPLIT.split(text) if s):
        if len(sentence) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_split_long_sentence(sentence, max_chars))
            continue
        if not cur:
            cur = sentence
        elif len(cur) + 1 + len(sentence) <= max_chars:
            cur = f"{cur} {sentence}"
        else:
            chunks.append(cur)
            cur = sentence
    if cur:
        chunks.append(cur)
    return chunks

def synthesize_long(
    text: str,
    synth: Callable[[str, str], object],
    out_path: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    workdir: str | None = None,
    stitcher: Callable[..., dict] | None = None,
    ext: str = "wav",
    **stitch_kwargs,
) -> dict:
    """Chunk ``text``, synthesize each chunk with ``synth(chunk, clip_path)``, then stitch the clips into
    ``out_path`` (default: :func:`audio_stitch.stitch`, which trims the seams + normalizes + joins).

    ``synth`` is injected so this is offline-testable; ``stitcher`` is injectable for the same reason.
    Returns a receipt: chunk count/texts, the ordered clip paths, and the stitch receipt.
    """
    chunks = chunk_text(text, max_chars=max_chars)
    if not chunks:
        raise ValueError("synthesize_long: text produced no chunks")
    stitch = stitcher or audio_stitch.stitch
    if workdir is None:
        workdir = tempfile.mkdtemp(prefix="long_narration_")
    os.makedirs(workdir, exist_ok=True)

    clip_paths: list[str] = []
    for i, chunk in enumerate(chunks):
        clip = os.path.join(workdir, f"clip_{i:03d}.{ext}")
        synth(chunk, clip)
        clip_paths.append(clip)

    receipt = stitch(clip_paths, out_path, **stitch_kwargs)
    return {
        "out": out_path,
        "chunks": len(chunks),
        "chunk_texts": chunks,
        "clips": clip_paths,
        "workdir": workdir,
        "stitch": receipt if isinstance(receipt, dict) else None,
    }
