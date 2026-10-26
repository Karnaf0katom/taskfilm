# Ads: composition, narration, music, and delivery

The `ad` path uses `taskfilm-ad/v1` rather than the fixed product-motion film.
Existing capture, motion, lesson, and reel commands still work. See
[AD-DIRECTION.md](AD-DIRECTION.md) for the full composition schema, layouts,
source crop contracts, and how agents can author additional templates.

## Direct and compose

Supply the product's own logo asset, local font, and colors in an ad spec. Use
real recorded video or image inputs. Scenes have independent durations; a recap
is optional. `media.in` is source seconds, `media.speed` is source seconds per
output second, and `media.crop` is `[x,y,width,height]` in source pixels.
Timing and crop validation refuses missing frames and out-of-bounds regions.

Some screen recordings have very sparse keyframes and stall a browser when
seeking to later shots. Create a seekable derivative before composing them:

```bash
taskfilm media prepare takes/original/screen.mp4 --out media/seekable.mp4
```

Use that derivative in the ad spec. Preparation keeps the frame dimensions,
uses one-second keyframes, removes source audio, and records both file hashes
in `seekable.preparation.json`. Retain the original take, capture sidecars and
preparation receipt with the editable project; the derivative is a render input.

```bash
taskfilm ad templates
taskfilm ad plan ad.json --out plan.json --history ad-history.json
taskfilm ad build ad.json --out cuts/portrait --history ad-history.json
taskfilm render cuts/portrait --output portrait.mp4
taskfilm ad rate my-ad 4 --history ad-history.json
```

Eight initial families change the spatial composition. Product/style matching,
recent-use penalties, and ratings guide automatic selection. An explicit scene
layout overrides selection. Export a family as a starting point for a genuinely
new composition; pass the new validated JSON to `--template-file`:

```bash
taskfilm ad templates --export hero-stage --out my-layout.json
# Change id, geometry, description, and fit tags in my-layout.json.
taskfilm ad build ad.json --template-file my-layout.json --out cuts/new
```

This is an extensible library, not a claim that hundreds of high-quality
templates have already been designed. Serialize writes to a shared history file.

## Narration and presenters

Google narration uses Gemini 2.5 Flash TTS directly on Linux. Set
`GOOGLE_API_KEY` or `GEMINI_API_KEY` in the process environment, then run
`taskfilm media narrate script.txt --provider google --voice Kore --out voice.wav`.
Credentials are excluded from receipts and caches. Google voice speed uses
pitch-preserving tempo adjustment; clips are cached including model and delivery style.

Local macOS narration can run on the Mac itself or through SSH. Explicit paid
providers use the existing `video-claw` package and its normal credential lookup.
Install it separately with `pip install video-claw`, or install a local checkout.
Narration outputs are cached by script, voice, provider, and rate; changing the
visual edit does not regenerate speech.

```bash
taskfilm media narrate script.txt --provider macos --voice 'Zoe (Premium)' \
  --ssh-host your-mac --out voice.wav
taskfilm media narrate script.txt --provider elevenlabs --out voice.wav
taskfilm media avatar --audio voice.wav --image your-presenter.png --out presenter.mp4
```

Avatar generation uses video-claw's fal.ai OmniHuman integration. Supply the
intended presenter image and matching narration. The generation command calls
the paid provider; it is optional. Use a short opening/closing clip, or the
composer's reserved presenter layout, to keep the demonstrated product clear.
An existing presenter video can also be composited during final delivery.

## Select actual music and mix

The starter catalog is `src/taskfilm/examples/ad/music-library.json` (copied by
`taskfilm init` into `ad/music-library.json`). It includes four acoustic/guitar
tracks, their mood tags, BPM, author source links, licenses, and required credits.
Downloads are explicit and preserve provenance/hash sidecars. Add your own tracks
with their licenses; no CapCut music is imported or presumed licensed.

```bash
taskfilm media music ad/music-library.json --tags acoustic rhythmic
taskfilm media music ad/music-library.json --fetch happy-alley --out music
taskfilm media mix audio.json --out mix.wav
```

Example `audio.json` (music metadata should come from its downloaded sidecar):

```json
{
  "schema": "taskfilm-audio/v1",
  "duration": 20,
  "music": {
    "path": "music/happy-alley.mp3",
    "commercial_use": true,
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "Copy the full attribution from the track's sidecar.",
    "gain_db": -12
  },
  "narration": [
    {"path": "voice.wav", "at": 0.3, "text": "The corresponding spoken line."}
  ]
}
```

Speech drives music ducking. The output targets -16 LUFS/-1.5 dBTP, retains music
credits and hashes in `mix.mix.json`, and emits timed caption JSON/SRT when voice
lines include `text`. Lines that extend past the film fail validation. SFX are
off unless explicitly supplied, with a limit of two types and four events.
Set `audio.path` in the ad spec to this finished mix.

Burn timed captions into the rendered output, using real font files if supplied:

```bash
taskfilm media finish portrait.mp4 --captions mix.captions.json \
  --font-dir brand/fonts --out portrait-ad.mp4
# Optional: --presenter presenter.mp4 --presenter-at 0.3 --presenter-size 0.18
```

`finish` preserves the existing narration/music, mutes the presenter video's
audio, and records the source/delivery hashes. Presenter timing must fit the ad.

## Queue automatic posts

See [PUBLISHING.md](PUBLISHING.md). Pass `audio_receipt` in the post manifest so
the queue carries required music credits into the post caption automatically.

A typical sample ad reuses one successful product capture, uses the product's
own wordmark and font, accelerates typing 6x, and pairs a natural voice with a
licensed music track. Keep development artifacts outside the source tree.
