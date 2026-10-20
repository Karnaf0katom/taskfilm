"""tts_registry.py — provider seam for text-to-speech, mirroring audiogen/registry.py + lip_sync_registry.

The DEFAULT is the FREE, commercial-safe ZeroGPU voices already wired in ``narration.select_tts_fn``
(kokoro for en, the Hebrew Space for he). **ElevenLabs is OPT-IN only**, behind ``ELEVENLABS_API_KEY``:
its voices are top-tier, but its free tier is ~10 min/month and carries NO commercial license
(attribution required, can't monetize) — so it is never the default for a monetized product.

``resolve_tts(lang, provider=...)`` returns either ``None`` (meaning "use ``narrate``'s built-in free
voice for this lang", which threads both ``voice`` and ``lang``) or an explicit ``tts_fn`` for an
opt-in provider. Feed the result straight into ``narration.narrate(..., tts_fn=resolve_tts(...))``.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

TtsFn = Callable[..., bytes]

# ElevenLabs TTS (opt-in, PAID/attribution). mp3 bytes decode fine downstream (audio_stitch runs ffmpeg).
_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # "Rachel" stock voice; override via ELEVENLABS_VOICE_ID
_DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
TTS_USER_AGENT = "edit-lane-tts/1.0"


class TtsNotConfigured(LookupError):
    """Raised when an explicitly requested TTS provider has no credentials (or is unknown)."""


class TtsKeysExhausted(RuntimeError):
    """Every key in a provider's pool answered with a quota/auth refusal for this one request."""


# --- key POOLS ------------------------------------------------------------------------------
# More keys = more quota. A 401/402/429 on one key rotates to the next, mirroring
# ``stt_adapters.GroqKeyPool``; any other status is the caller's bug and surfaces at once.
# The gitignored ``.agent/secrets/<provider>.keys`` file contributes EVERY non-comment line
# (these readers used to take only the first, so extra keys bought nothing).
_ROTATE_STATUSES = (401, 402, 429)


def _secrets_pool(filename: str) -> list[str]:
    """Every non-comment line of ``.agent/secrets/<filename>``, in order. Missing file = empty."""
    directory = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        cand = os.path.join(directory, ".agent", "secrets", filename)
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as fh:
                return [line.strip() for line in fh if line.strip() and not line.startswith("#")]
        directory = os.path.dirname(directory)
    return []


def _env_pool(*names: str) -> list[str]:
    """Comma-separated keys from the first env var that is set, in declaration order."""
    out: list[str] = []
    for name in names:
        out.extend(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())
    return out


class _FishRotation:
    """Share fair scheduling and cooldowns across Fish speakers in this process."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cursors = {}
        self.cooldowns = {}

    def order(self, keys):
        with self.lock:
            start = self.cursors.get(keys, 0) % len(keys)
            self.cursors[keys] = start + 1
            ordered = keys[start:] + keys[:start]
            now = time.monotonic()
            return tuple(k for k in ordered if self.cooldowns.get(k, 0) <= now)

    def refuse(self, key, error):
        delay = 60 if error.code == 429 else 300
        try:
            delay = max(delay, float(error.headers.get("Retry-After", delay)))
        except (TypeError, ValueError, AttributeError):
            pass
        with self.lock:
            self.cooldowns[key] = time.monotonic() + delay


_FISH_ROTATION = _FishRotation()


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
    """The ordered ElevenLabs key pool: env ``ELEVENLABS_API_KEYS``/``ELEVENLABS_API_KEY`` first,
    else EVERY line of the gitignored ``.agent/secrets/elevenlabs.keys``."""
    keys = _env_pool("ELEVENLABS_API_KEYS", "ELEVENLABS_API_KEY") or _secrets_pool("elevenlabs.keys")
    return tuple(dict.fromkeys(keys))


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


def _elevenlabs_configured() -> bool:
    return bool(_elevenlabs_key())


def _elevenlabs_tts_fn(*, model_id: str = _DEFAULT_ELEVENLABS_MODEL) -> TtsFn:
    """Build a ``tts_fn`` that speaks one chunk via the ElevenLabs TTS API (opt-in; real network call).

    The POST only fires when this fn is actually invoked — i.e. a caller opted in with a key. Returns
    the raw audio bytes; ``narration.narrate`` writes them and ``audio_stitch`` re-encodes on stitch."""
    keys = _elevenlabs_keys()
    if not keys:
        raise TtsNotConfigured("ELEVENLABS_API_KEY not set (env or .agent/secrets/elevenlabs.keys)")

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


# Vertex Chirp3-HD TTS (Cloud Text-to-Speech). Billed to the GCP project's CREDITS, not a per-token key.
# Needs the OAuth token + a quota-project header (texttospeech is NOT a Vertex publisher endpoint).
# Default voice en-US-Chirp3-HD-Charon; override via VERTEX_TTS_VOICE or the per-call voice arg.
_VERTEX_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
_DEFAULT_CHIRP_VOICE = "en-US-Chirp3-HD-Charon"


def _vertex_access_token() -> str | None:
    tok = os.environ.get("VERTEX_ACCESS_TOKEN", "").strip()
    if tok:
        return tok
    try:
        import subprocess

        out = subprocess.run(["gcloud", "auth", "print-access-token"],
                             capture_output=True, text=True, timeout=30)
        return (out.stdout or "").strip() or None
    except Exception:
        return None


def _vertex_tts_configured() -> bool:
    return bool(_vertex_access_token())


def _vertex_tts_fn(*, access_token: str | None = None, project: str | None = None,
                   urlopen=None) -> TtsFn:
    """Build a ``tts_fn`` that speaks one chunk via Chirp3-HD on the GCP credits (real network call)."""
    import base64

    token = access_token or _vertex_access_token()
    if not token:
        raise TtsNotConfigured("provider 'chirp'/'vertex' requested but no GCP access token "
                               "(VERTEX_ACCESS_TOKEN or `gcloud auth login`)")
    project = (project or os.environ.get("VERTEX_TTS_PROJECT") or os.environ.get("VERTEX_PROJECT")
               or "project-8adfab6d-0936-4f24-b03")

    def speak(text: str, *, lang: str | None = None, voice: str | None = None) -> bytes:
        voice_name = voice or os.environ.get("VERTEX_TTS_VOICE") or _DEFAULT_CHIRP_VOICE
        language = lang or "-".join(voice_name.split("-")[:2]) or "en-US"
        body = json.dumps({
            "input": {"text": text},
            "voice": {"languageCode": language, "name": voice_name},
            "audioConfig": {"audioEncoding": "MP3"},
        }).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 — fixed, trusted Google TTS host
            _VERTEX_TTS_URL, data=body, method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                     "X-Goog-User-Project": project, "User-Agent": TTS_USER_AGENT},
        )
        with (urlopen or urllib.request.urlopen)(req, timeout=60) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        audio = base64.b64decode(data.get("audioContent", ""), validate=True)
        if not audio:
            raise TtsNotConfigured("Google TTS returned no audio")
        return audio

    return speak


# Fish Audio TTS (fish.audio) — very natural/expressive; the free model "s2.1-pro-free" needs no credits.
# Key via env FISHAUDIO_API_KEY / FISH_API_KEY, else the gitignored .agent/secrets/fishaudio.keys.
_FISHAUDIO_TTS_URL = "https://api.fish.audio/v1/tts"
_DEFAULT_FISH_MODEL = "s2.1-pro-free"


def fishaudio_api_keys() -> tuple[str, ...]:
    """The ordered Fish Audio key pool: env ``FISHAUDIO_API_KEYS``/``FISHAUDIO_API_KEY``/``FISH_API_KEY``
    first, else EVERY line of the gitignored ``.agent/secrets/fishaudio.keys``.

    Each Fish key carries its own free-model allowance, so adding lines to that file is what
    actually widens the pilot's headroom — the reader used to stop at the first line."""
    keys = (_env_pool("FISHAUDIO_API_KEYS", "FISHAUDIO_API_KEY", "FISH_API_KEY")
            or _secrets_pool("fishaudio.keys"))
    return tuple(dict.fromkeys(keys))


def _fishaudio_key() -> str | None:
    """The first Fish key, or None. Kept as the single seam callers/tests monkeypatch."""
    keys = fishaudio_api_keys()
    return keys[0] if keys else None


def _fishaudio_keys() -> tuple[str, ...]:
    """Pool to try for one request. An overridden ``_fishaudio_key`` means exactly that key."""
    first = _fishaudio_key()
    if not first:
        return ()
    pool = fishaudio_api_keys()
    return pool if pool and pool[0] == first else (first,)


def _fishaudio_configured() -> bool:
    return bool(_fishaudio_key())


def _fishaudio_tts_fn(*, model: str | None = None) -> TtsFn:
    """Build a ``tts_fn`` that speaks one chunk via Fish Audio (returns mp3 bytes).

    Model header = explicit ``model`` then ``FISHAUDIO_MODEL`` then the free ``s2.1-pro-free``. Voice =
    explicit per-call ``voice`` then ``FISHAUDIO_VOICE_ID`` (a fish.audio reference_id). Missing voice is
    fail-closed: never rely on a provider account default."""
    keys = _fishaudio_keys()
    if not keys:
        raise TtsNotConfigured("FISHAUDIO_API_KEY not set (env or .agent/secrets/fishaudio.keys)")
    model_name = model or os.environ.get("FISHAUDIO_MODEL") or _DEFAULT_FISH_MODEL

    def speak(text: str, *, lang: str | None = None, voice: str | None = None) -> bytes:
        ref = (voice or "").strip() or os.environ.get("FISHAUDIO_VOICE_ID", "").strip()
        if not ref:
            raise TtsNotConfigured("Fish Audio requires an explicit reference_id: pass voice=... or set FISHAUDIO_VOICE_ID")
        payload = {"text": text, "format": "mp3", "reference_id": ref}
        body = json.dumps(payload).encode("utf-8")

        def build(api_key: str) -> urllib.request.Request:
            return urllib.request.Request(  # noqa: S310 — fixed, trusted Fish Audio host
                _FISHAUDIO_TTS_URL, data=body, method="POST",
                headers={"Authorization": "Bearer " + api_key, "model": model_name,
                         "Content-Type": "application/json", "User-Agent": TTS_USER_AGENT},
            )

        # A key with no credit answers 402 even on the free model; rotate rather than fail the take.
        return _rotating_post(keys, build, "Fish Audio", rotation=_FISH_ROTATION)

    return speak


def resolve_tts(lang: str = "en-us", *, provider: Optional[str] = None,
                model: str | None = None) -> Optional[TtsFn]:
    """Pick a TTS engine for ``narration.narrate(tts_fn=...)``.

    * ``provider`` in ``(None, "free", "default")`` -> the API default: Fish Audio if a Fish key is
      configured, else ElevenLabs if its key is configured, else ``TtsNotConfigured`` (fail-closed).
      The old Kokoro/Hebrew Hugging-Face-Space default was RETIRED 2026-08-04 (HF access dropped +
      basic quality) — we rely on the Fish + ElevenLabs APIs, never a silent HF fallback.
    * ``provider == "elevenlabs"`` -> the opt-in ElevenLabs speaker; raises ``TtsNotConfigured`` if
      ``ELEVENLABS_API_KEY`` is unset (fail loud rather than silently downgrade to a different voice).
    * ``provider == "fish"`` / ``"fishaudio"`` -> Fish Audio; optional ``model`` is threaded only here.
    * any other value -> ``TtsNotConfigured``.

    NOTE: both providers' FREE tiers are non-commercial — a monetized product needs a PAID Fish or
    ElevenLabs plan regardless of which resolves here.
    """
    if provider in (None, "free", "default"):
        if _fishaudio_configured():
            return _fishaudio_tts_fn(model=model)
        if _elevenlabs_configured():
            return _elevenlabs_tts_fn()
        raise TtsNotConfigured(
            "no default TTS configured — the Kokoro/HF default was retired. Add a Fish key "
            "(FISHAUDIO_API_KEY or .agent/secrets/fishaudio.keys) or ELEVENLABS_API_KEY."
        )
    if provider == "elevenlabs":
        if not _elevenlabs_configured():
            raise TtsNotConfigured("provider 'elevenlabs' requested but ELEVENLABS_API_KEY is not set")
        # ``model`` was already threaded to Fish; ElevenLabs needs it for the same reason. Measured
        # against /v1/models on 2026-08-29: eleven_multilingual_v2 does NOT list Hebrew, and asking
        # it for Hebrew returns audio that is not the sentence — a failure with no error attached.
        # Only eleven_v3 / eleven_v3_conversational cover it, so a caller must be able to say so.
        return _elevenlabs_tts_fn(model_id=model or _DEFAULT_ELEVENLABS_MODEL)
    if provider in ("chirp", "vertex"):
        if not _vertex_tts_configured():
            raise TtsNotConfigured("provider 'chirp'/'vertex' requested but no GCP access token "
                                   "(VERTEX_ACCESS_TOKEN or `gcloud auth login`)")
        return _vertex_tts_fn()
    if provider in ("fish", "fishaudio"):
        if not _fishaudio_configured():
            raise TtsNotConfigured("provider 'fish'/'fishaudio' requested but no key "
                                   "(FISHAUDIO_API_KEY or .agent/secrets/fishaudio.keys)")
        return _fishaudio_tts_fn(model=model)
    raise TtsNotConfigured(f"unknown TTS provider: {provider!r}")
