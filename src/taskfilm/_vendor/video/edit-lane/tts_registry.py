"Opt-in ElevenLabs speech using only the caller's environment key."

from __future__ import annotations

import json

import os

import urllib.error

import urllib.request

from typing import Callable, Optional

TtsFn = Callable[..., bytes]

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

_DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # "Rachel" stock voice; override via ELEVENLABS_VOICE_ID

_DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"

TTS_USER_AGENT = "edit-lane-tts/1.0"

class TtsNotConfigured(LookupError):
    """Raised when an explicitly requested TTS provider has no credentials (or is unknown)."""

class TtsKeysExhausted(RuntimeError):
    """Every key in a provider's pool answered with a quota/auth refusal for this one request."""

_ROTATE_STATUSES = (401, 402, 429)

def _env_pool(*names: str) -> list[str]:
    """Comma-separated keys from the first env var that is set, in declaration order."""
    out: list[str] = []
    for name in names:
        out.extend(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())
    return out

def _rotating_post(keys, build_request, provider: str, *, rotation=None) -> bytes:
    """POST with each key in turn; only a quota/auth status rotates to the next key."""
    last: urllib.error.HTTPError | None = None
    candidates = rotation.order(keys) if rotation else keys
    if not candidates:
        raise TtsKeysExhausted(f"{provider} keys are cooling down; retry later")
    for key in candidates:
        try:
            with urllib.request.urlopen(build_request(key), timeout=60) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in _ROTATE_STATUSES:
                raise
            last = exc
            if rotation:
                rotation.refuse(key, exc)
    raise TtsKeysExhausted(
        f"all {len(tuple(keys))} {provider} key(s) refused this request"
        + (f" (last HTTP {last.code})" if last is not None else "")
    )

def elevenlabs_api_keys() -> tuple[str, ...]:
    return tuple(dict.fromkeys(_env_pool("ELEVENLABS_API_KEY")))

def _elevenlabs_key() -> str | None:
    """The first ElevenLabs key, or None. Kept as the single seam callers/tests monkeypatch."""
    keys = elevenlabs_api_keys()
    return keys[0] if keys else None

def _elevenlabs_keys() -> tuple[str, ...]:
    """Pool to try for one request. An overridden ``_elevenlabs_key`` means exactly that key."""
    first = _elevenlabs_key()
    if not first:
        return ()
    pool = elevenlabs_api_keys()
    return pool if pool and pool[0] == first else (first,)

def _elevenlabs_tts_fn(*, model_id: str = _DEFAULT_ELEVENLABS_MODEL) -> TtsFn:
    """Build a ``tts_fn`` that speaks one chunk via the ElevenLabs TTS API (opt-in; real network call).

    The POST only fires when this fn is actually invoked — i.e. a caller opted in with a key. Returns
    the raw audio bytes; ``narration.narrate`` writes them and ``audio_stitch`` re-encodes on stitch."""
    keys = _elevenlabs_keys()
    if not keys:
        raise TtsNotConfigured("ELEVENLABS_API_KEY not set")

    def speak(text: str, *, lang: str | None = None, voice: str | None = None) -> bytes:
        voice_id = voice or os.environ.get("ELEVENLABS_VOICE_ID") or _DEFAULT_ELEVENLABS_VOICE_ID
        url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)
        body = json.dumps({"text": text, "model_id": model_id}).encode("utf-8")

        def build(api_key: str) -> urllib.request.Request:
            return urllib.request.Request(  # noqa: S310 — fixed, trusted ElevenLabs host
                url, data=body, method="POST",
                headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg",
                         "User-Agent": TTS_USER_AGENT},
            )

        # A spent character quota answers 401; the next key in the pool still has its own quota.
        return _rotating_post(keys, build, "ElevenLabs")

    return speak

def resolve_tts(lang="en", *, provider=None, model=None):
    if provider != "elevenlabs":
        raise TtsNotConfigured("Choose the explicit elevenlabs provider")
    return _elevenlabs_tts_fn(model_id=model or _DEFAULT_ELEVENLABS_MODEL)
