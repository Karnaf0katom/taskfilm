# Taskfilm ads: product evidence, composed deliberately

`taskfilm.ad` authors editable HyperFrames projects from `taskfilm-ad/v1` specs. It supports one to forty scenes, 0.5–30 seconds each, up to 180 seconds total. A 15–30 second ad should normally show one promise, one or two pieces of evidence, and a clear next action. There is no required recap, three-act structure, typing animation, generated soundtrack, or extruded wordmark.

## Integration

```python
from taskfilm.ad import build, main, plan, validate

project = build("ad.json", "/tmp/my-ad-cut")  # returns an absolute pathlib.Path
# Parent CLI dispatch:
main(["build", "ad.json", "--out", "/tmp/another-cut"])
```

`build`, `plan`, and `validate` accept a JSON file path or a dictionary. Relative asset paths resolve beside the spec file, or against `base_dir` (current directory for dictionaries). All three accept `history` and `template_paths`. Build requires a history **file path** when recording history. Planning can also accept an in-memory history list. Outputs must be absent or empty; rebuilding into another directory preserves manual edits.

Run from this checkout through the parent CLI:

```sh
PYTHONPATH=src python3 -m taskfilm ad templates
PYTHONPATH=src python3 -m taskfilm ad plan ad.json --out plan.json
PYTHONPATH=src python3 -m taskfilm ad validate ad.json
PYTHONPATH=src python3 -m taskfilm ad build ad.json --out /tmp/ad-cut --history /tmp/ad-history.json
PYTHONPATH=src python3 -m taskfilm ad rate my-ad 5 --history /tmp/ad-history.json
cd /tmp/ad-cut
npm run check
npm run dev
npm run render -- --output /tmp/ad.mp4
```

Generated scripts pin HyperFrames **0.8.134**, matching the parent CLI default. No package installation or publishing occurs in the Python builder. The HTML template is embedded in `ad.py`, so the existing package configuration includes it without a package-data change. Projects reference GSAP 3.14.2 on jsDelivr unless `gsap.min.js` is already available in the existing vendor asset directory. First render therefore requires network access in the default checkout; brand/media assets are local. For offline use, vendor that exact GSAP version into the generated project's assets and update its script URL. If automatic browser discovery requests an unavailable Chrome build, set `HYPERFRAMES_BROWSER_PATH` to an existing Chrome/headless-shell binary. Raw sources with sparse keyframes can stall browser preview seeking even when the frame-extraction render succeeds; retain originals and use the parent media preparation path when a seekable derivative is needed.

## Spec

```json
{
  "schema": "taskfilm-ad/v1",
  "id": "my-ad",
  "format": "portrait",
  "product": "booking",
  "style": "calm",
  "brand": {
    "name": "Acme Studio",
    "logo": "brand/logo.svg",
    "font": "brand/manrope-bold.ttf",
    "font_license": "brand/OFL.txt",
    "colors": {"background": "#f5f1eb", "text": "#292623", "accent": "#782596"}
  },
  "scenes": [
    {"id": "promise", "layout": "type-led", "duration": 2.5,
     "headline": "Your week, in focus."},
    {"id": "proof", "layout": "hero-stage", "duration": 4,
     "headline": "Pick your date range.",
     "media": {"path": "takes/screen.mp4", "type": "video", "in": 17,
               "speed": 3, "crop": [2300, 560, 1500, 1050]}},
    {"id": "close", "layout": "brand-close", "duration": 3,
     "headline": "Know your numbers.", "body": "example.com"}
  ],
  "audio": {"path": "audio/finished-mix.wav"}
}
```

The example's clip coordinates and anchors must match your actual recording. `validate` probes every source with ffprobe; it does not infer dimensions from filenames. `in` is source seconds. Speed is source seconds per output second: a 4-second shot at 3× consumes 12 seconds. Values outside 0.25–8×, negative trims, reads past the source's duration, and out-of-source crops fail. Crop coordinates are **source pixels**, `[x,y,width,height]`, not fractions or right/bottom coordinates. The entire explicit crop is contained inside its composition slot, preserving aspect ratio. No extra crop, motion interpolation, UI reconstruction, cursor overlay, or synthetic workflow is introduced. Rotated/non-square-pixel footage must be normalized explicitly first.

`media` is optional. A still has `type: "image"` and may have a crop, but cannot have `in` or `speed`. Animated images must become explicit video clips. The logo must be a real local SVG or raster image. `font` is the local `.ttf` or `.otf` body/caption face; optional `headline_font` supplies a separate headline face (otherwise headlines use `font`); omitted fonts use bundled Manrope with a warning. Typography is measured using the supplied font; overlong copy fails or selects another fitting automatic layout. Headlines are capped at 110 characters and bodies at 220. The logo keeps its native artwork and aspect ratio. Supply a tight SVG viewBox if the original includes large internal whitespace. Optional `brand.font_license` names a local license file; it is copied byte-for-byte, hashed in the source evidence receipt, and referenced by the portable spec. Font/asset usage rights remain the author's responsibility.

`audio.path` accepts the parent's finished music/narration mix. It must contain an audio stream covering the full ad; a longer mix is cut to the ad duration. Source clip audio is muted. Without `audio`, the project is silent and the plan reports that fact. Music selection, licensing, beat alignment, narration, avatar generation, and lip sync belong to the parent's audio/media path. An avatar can be supplied as an ordinary video scene or through the optional presenter overlay below.

## Presenter and explicit captions

```json
{
  "presenter": {
    "path": "media/presenter.mp4",
    "scene_ids": ["promise", "close"],
    "placement": "bottom-right",
    "size": 0.22
  }
}
```

This optional top-level object consumes the parent's already generated/lip-synced local video. `scene_ids` must be unique existing scene IDs; only those scenes display the presenter. The presenter follows **global ad time**: a scene starting at 8 seconds uses the presenter video from 8 seconds. The source must cover the end of the last selected scene. Do not pass a montage of only selected narration intervals unless it is first aligned to this global clock. Presenter audio is muted; `audio.path` remains the sole audible track.

`placement` defaults to `bottom-right` and is the only supported placement. `size` defaults to 0.22, ranges from 0.12 to 0.35, and defines the maximum side as a fraction of the **shorter canvas dimension**. The video's native aspect ratio is preserved. This bounds portrait presenters in landscape output as well as portrait output. The presenter stays inside the mobile-safe rectangle. The planner reserves a footer band, reflows the family's logo/copy/product boxes above it, then remeasures all text. Overlap or unreadable copy is rejected; the presenter never obscures product evidence.

A scene may supply `caption: "Explicit narration text for this scene."` (up to 180 characters). It appears for that whole scene in a reserved safe footer, beside the presenter when one is present. Captions use the body font and must fit at most three readable lines; excessive text fails. Caption-only scenes also reserve the footer. These are authored scene captions, not transcription, word highlighting, or automatic timing. `body` remains ordinary scene copy. No additional animation or sound family is introduced.

## Eight composition families

| Family | Arrangement | Suitable use |
| --- | --- | --- |
| `hero-stage` | Large centered evidence under a concise promise | Product hero, first proof |
| `editorial-split` | Asymmetric copy column and product panel | Reports, editorial explanation |
| `proof-strip` | Wide evidence above a short caption | An outcome that can speak first |
| `detail-poster` | Tall narrow evidence and a side note | Mobile UI, tightly cropped detail |
| `quiet-card` | Smaller centered evidence with whitespace | Calm, premium, wellness |
| `caption-rail` | Product-dominant evidence with compact caption rail | Technical demonstration |
| `type-led` | Large statement and a smaller optional inset | Hook, objection, short promise |
| `brand-close` | Authentic logo lockup, CTA, optional thumbnail | Closing card |

Each has authored portrait, landscape, and square geometry. They differ in hierarchy, evidence placement, proportions, and alignment. Automatic selection ranks exact `product` and `style` tags, matching-product/style feedback, the five most recent ads, and layouts already used in this ad. Ties sort by template ID, so results are reproducible. Explicit top-level `template` or scene `layout` overrides ranking (scene wins); the planner still validates copy fit. No-media scenes reclaim unused evidence space. Inspect `AD-PLAN.json` for scores and selection reasons.

History is an optional JSON array ordered oldest first, with records `{ad_id, templates: [ids], product, style, rating: null|1..5}`. Builds append one record; `rate` updates the latest matching ad. A rating applies to all families used in that ad, filtered by product/style when ranking; this is an inspectable preference signal, not measured conversion optimization. Keep separate history files for independent brands and serialize writes; concurrent history writers are not supported. User-selected layouts can repeat intentionally.

## Extending templates

Export a starting interface and give the new template a unique ID:

```sh
PYTHONPATH=src python3 -m taskfilm ad templates --export editorial-split --out custom.json
PYTHONPATH=src python3 -m taskfilm ad build ad.json --template-file custom.json --out /tmp/custom-cut
```

External templates use `taskfilm-ad-template/v1`: exactly `schema`, `id`, `name`, `description`, `products`, `styles`, and `frames`. Each format's frame has exactly `copy`, `media`, `logo` (normalized `[x,y,width,height]` rectangles), `headline_size` (40–160 canvas pixels), `align` (`left` or `center`), and `radius` (0–40 pixels). Every rectangle must remain within the format's safe area and must not overlap another content rectangle. Duplicate IDs and unknown fields fail. External templates cannot execute code or inject markup. Future agents can author compositions within this contract; arbitrary multi-panel layouts or richer motion would require a reviewed interface version. The dedicated presenter overlay follows its separate validated safe-area contract.

Portrait essential content stays inside x=6–88%, y=9–79%; square inside x=6–92%, y=7–87%; landscape inside x=5–95%, y=6–92%. These are conservative defaults, not a guarantee against every platform's overlays. Full-frame backgrounds remain edge-to-edge. Author copy/background contrast must reach 4.5:1. Text uses measured line breaks and a readable size floor, never CSS clipping or an ellipsis. The enforced motion vocabulary contains at most two families: cuts and a 240ms copy fade/lift. Presenter and subtitle overlays use cuts only. Rounded evidence edges are static. Product frames remain stable. There are no default swooshes, particles, flashes, fake browser chrome, or sound effects.

## Editable output and evidence

The project includes `index.html`, `index.motion.json`, `hyperframes.json`, `package.json`, copied media/fonts/logo/audio, portable `ad.json`, untouched input `AD-SOURCE.json`, `AD-PLAN.json`, `EDIT-DECISIONS.json`, and JSON copies of selected templates. Capture `session.json`, `input.jsonl`, `beats.jsonl`, and `windows.jsonl` beside a media source are copied into `evidence/`. Every preserved source gets an absolute original path, SHA-256, byte count, and project-relative copied path. Originals are never rewritten or shortened. `AD-SOURCE.json` may contain private local paths; review metadata before publishing a project.

To regenerate a project from its portable `ad.json`, built-in templates need no flags; custom templates require the corresponding `--template-file templates/<id>.json`. The portable spec pins each chosen layout, so historical ranking changes cannot alter it. HTML remains directly editable; regenerating from a spec does not preserve manual HTML edits.

HyperFrames owns visibility and source seeking. Each timed media element carries global `data-start`, `data-duration`, source `data-media-start`, and `data-playback-rate`. It is never nested in another timed scene wrapper. GSAP animates only caption children through a paused `window.__timelines.main` timeline. Run HyperFrames check and snapshot after editing, and review playback with the final audio mix before posting. Media-valid and layout-valid do not establish that marketing claims are true: review the actual captured outcome.

## Worked example

A typical product ad starts from one successful capture of a single workflow: for example, a reports screen where the viewer picks a date range, applies it, and opens one result. Use the product's own exported logo vector, its licensed product font for `brand.font` with the license file as `brand.font_license`, and colors from the product's brand spec. Preserve the actual logo instead of spelling the brand in generic 3D letters. Note the source click anchors (for example: range picker, first date, second date, apply, result detail) from `input.jsonl`, and check adjacent frames for the final visual state.

Suggested 21-second edit: 2.5s promise; 4s date input at 3×; 4.5s apply/result at 1×; 6s result detail at 1×; 4s CTA. Prefer hero-stage → proof-strip or editorial-split for evidence, then brand-close. Do not show every tap or replay three tiny screenshots. Crop tightly around the panel being shown; for portrait, choose a narrower truthful detail and make sure the displayed numbers remain readable. Do not present demo data as a real customer's results.

## Playback-speed verification

HyperFrames 0.8.134's actual MP4 renderer honors `data-playback-rate`. A 6× regression fixture starts its scene at ad time 1s and consumes source from 0.5s. Rendered output at 1.2s, 1.5s, and 1.8s matches source frames at 1.7s, 3.5s, and 5.3s respectively, with decoded RGB error at most 2 per channel in the recorded run. Each sample differs decisively from 1× playback. This verifies source offset, nonzero scene start, and acceleration together; it is not an attribute-presence test. Originals remain unchanged, with no hidden pre-retiming.

The real Chrome/render regression is opt-in because it needs Node/npm, the pinned HyperFrames runtime, network for GSAP, and a working browser:

```sh
TASKFILM_RENDER_TESTS=1 .venv/bin/python -m pytest tests/test_ads.py -q
```

Set `HYPERFRAMES_BROWSER_PATH` if browser discovery needs an explicit existing binary. Default test runs skip this render test. Preview seeking of sparse-keyframe captures remains a separate limitation; a successful runtime render does not remove that source characteristic.
