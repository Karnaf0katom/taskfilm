# Taskfilm workflows

Install Taskfilm using the [README](../README.md), then follow these recipes.

## Try one real task

```bash
taskfilm init demo
taskfilm story --request demo/request.json --story demo/feature.json --out lesson-plan
taskfilm story --request demo/request.json --story demo/promo.json --out promo-plan
python -m http.server 8765 --bind 127.0.0.1 --directory demo/taskboard
```

Leave that local server running and open another terminal in the same virtual
environment:

```bash
taskfilm capture validate demo/capture.json
taskfilm capture rec demo/capture.json --out-dir takes --no-burn-captions
# Use the exact take directory printed by the recorder:
taskfilm edit takes/YOUR-TAKE --no-retime
taskfilm compose takes/YOUR-TAKE --out lesson-composition --no-title --width 1280 --height 720 --max-scale 1 --note-top 4
taskfilm render lesson-composition --output lesson.mp4
```

`YOUR-TAKE` is the generated timestamped directory, not an extra folder to create.
The sample is a working original task app: add **Ship the demo**, complete it and
select **Completed**. It stores its tasks locally and needs no signed-in account.
The original Taskboard sample uses browser local storage and has no shared backend.

The story commands export plans and briefs. They report capture and visual review
as pending. A plan alone is not a finished film. `compose` uses the recorded beat
labels, footage and click-based camera moves; it does not automatically execute
the product-story brief. Review its result before using it as a lesson or advert.

The basic capture adapter above is useful for an unhurried lesson. Try the
separate examples below to see the motion work.

## Try the animation study

`init` includes an original 24-second motion lab with four editable scenes:
masked kinetic type, SVG path drawing and shape interpolation, a perspective
card composition, and an animated wordmark. Its design and timeline are separate
from the Taskboard lesson. The study deliberately uses silence.

```bash
taskfilm render demo/motion-lab --output motion-lab.mp4
```

Edit `demo/motion-lab/compositions/*.html` to change its design and choreography.
HyperFrames owns the timeline and render. These are HTML/SVG motion graphics;
this release does not read Adobe After Effects `.aep` projects.

## Try the product-film kit

The existing product-motion owner authors a 31-second launch treatment with
a kinetic opening, 3D window reveal, directed camera, a click on the beat,
result lift, three-shot recap and animated end card. It supports landscape
and portrait layouts. This fixed film structure is separate from `compose`.

```bash
python -m pip install '.[motion]'
cp demo/motion-spec.json demo/spec.json
# Keep the same local Taskboard server running.
taskfilm capture rec demo/motion-capture.json --out-dir demo/takes --no-burn-captions
# Use the exact timestamped take path printed above:
taskfilm motion demo --take demo/takes/YOUR-TAKE --format landscape
taskfilm render demo/cuts/landscape --output taskboard-motion.mp4
taskfilm motion demo --take demo/takes/YOUR-TAKE --format portrait
taskfilm render demo/cuts/portrait --output taskboard-motion-portrait.mp4
```

The supplied capture is 3840×2160 with 3× CSS zoom: the film's cameras use real
source pixels. The editable spec identifies source regions and action anchors;
adjust those when you change the app. DOM assertions retain the actual task
result. Capture checks do not replace viewing the finished cut.

The sample enables `source.prepare_for_seek`: the kit prepares a 30fps render
copy with one-second keyframes for reliable camera seeking. It keeps the original
recording and stores both source and render-copy hashes in the edit decisions.
The sample's `layout.landscape.slab` places its callouts above the task result;
adjust that box when your app's result occupies another part of the frame.
Its `edit.recap_stills` uses real recorded frames for the three animated recap
cards. Their timestamps, crops and hashes are retained in the edit decisions.

The example score and effects are synthesized by the included owner using fixed
seeds, with no provider call or downloaded music. For your own licensed WAV,
replace `music.synthesis` with `music.file`, set `music.relative_to` to `film`,
and supply the measured `period`, `phase` and `offset`. `--no-audio` skips mix
generation. The kit keeps the original take and exports `EDIT-DECISIONS.json`.

## Make a narrated Excalidraw motion promo

The separate 48-second treatment adds masked type, a perspective browser
entrance, directed camera moves and animation of the retained native diagram.
It keeps every browser source interval, with measured playback rates between
0.5× and 2×. It produces editable HTML/SVG, not an Adobe `.aep` project.

First use the [Excalidraw capture recipe](../src/taskfilm/examples/oss-showcases/README.md)
or a retained take from the editable-project download. Provide a music file
covering the full 48 seconds and six narration cues in `narration.json`. Each cue
contains `path`, `sha256`, `at`, `until` and `text`; paths name audio files beside
the JSON. The script checks actual voice durations before authoring the film.

```bash
python demo/oss-showcases/build-excalidraw-promo.py \
  --take takes/YOUR-EXCALIDRAW-TAKE \
  --narration audio/narration.json --music audio/music.wav --out excalidraw-promo
taskfilm render excalidraw-promo --output excalidraw-promo.mp4
```

Use cue windows 0.6–6.8, 7.7–20.8, 21.5–30.8, 31.4–36.8, 37.4–41.8 and
42.5–47.8 seconds. The downloadable showcase contains its actual script and
measured timings. Voice generation happens separately using your own provider
account. Review the audio mix and encoded frames before sharing a new version.

## Story planning modes

| Purpose | Story mode | Direction |
|---|---|---|
| Teach a feature | `feature_demo` | One task, natural-speed actions, enough time to read the result |
| Promote a product | `saas_launch` | Problem, a small real workflow, payoff, supplied call to action |
| Show an OSS tool | `github_review` | Pinned source, real task, fit and limitation, source attribution |

For OSS planning, supply a pinned repo pack from `taskfilm repo-pack --help`, then
pass `--repo-pack` to `taskfilm story`. Source documents establish attributed
source assertions; recordings and retained results establish runtime behaviour.
The repo-pack command reads/clones source; it does not run arbitrary repository
setup instructions. Repository build/sandbox execution is outside this alpha.

To try the third mode with Taskfilm itself, run this from a clone of the public
release after `taskfilm init demo`. Use an HTTPS GitHub remote for this recipe;
if your origin uses SSH, pass its HTTPS GitHub URL to `repo-pack` instead.
The sample helper checks that your local README
matches the pinned document before binding its source references:

```bash
mkdir oss-source
cd oss-source
taskfilm repo-pack "$(git -C .. remote get-url origin)" --ref "$(git -C .. rev-parse HEAD)"
cd ..
python demo/prepare-oss-review.py --repo-pack oss-source/repo-pack.json --readme README.md --out demo/oss-request.json
taskfilm story --request demo/oss-request.json --story demo/oss.json --repo-pack oss-source/repo-pack.json --out oss-plan
```

This produces an attributed source plan for the original Taskboard sample.
Record and review its real task using the capture commands above. For another
OSS tool, supply that tool's own claims, actions, fit and limitation.

## Commands

| Command | Existing owner |
|---|---|
| `taskfilm story` | Director product-story planner |
| `taskfilm capture` | Browser recorder, DOM discovery and capture validation |
| `taskfilm edit` | Capture edit planner |
| `taskfilm compose` / `taskfilm reel` | Landscape / portrait HyperFrames adapters |
| `taskfilm motion` | Existing product-motion film authoring kit |
| `taskfilm render` | The composition's pinned HyperFrames CLI |
| `taskfilm repo-pack` | Pinned repository source pack |
| `taskfilm package` | Evidence-bound HTML companion or finished release showcase |
| `taskfilm doctor` / `taskfilm init` | Install diagnostics / original sample files |
| `taskfilm skill DIRECTORY` | Copy the included agent skill to your chosen skill folder |

Use `taskfilm skill ~/.codex/skills/taskfilm-video` for Codex, or choose the skill
directory used by your agent. Existing destinations are never overwritten.
Run an owner command with `--help` to see its input contract. The sample brand
and Manrope font are included. `init` copies an editable brand pack and the
font notice into `demo/brand/`. Change its wordmark/palette, or add your own
pack and licensed fonts, then pass `--brand-dir demo/brand` to `story`.
The request's `brand.pack` selects the JSON filename. Brand validation and
digest generation still use the existing owner.
For a lesson that needs the whole UI visible, pass `--max-scale 1` to `compose`.
Use `--note-top` to put labels in a clear strip above the recorded toolbar.

## Privacy and portability

Fresh browser contexts are the default. Keystroke characters are redacted in the
event log by default, while the screen still records what is visible. Use sample
accounts and inspect footage before sharing. Auth states stay outside take
bundles. `capture auth` is an explicit opt-in; don't commit browser profiles or
cookies. Keep scripts you run and the pages they target under your control.

`CAPTURE_LANE_BROWSER_PATH` selects an existing Chromium executable.
`PLAYWRIGHT_BROWSERS_PATH` is honoured by Playwright for its browser cache.
`CAPTURE_LANE_RECORDINGS` changes the recording destination.
`CAPTURE_LANE_AUTH_HOME` changes private auth storage.
The wheel carries the two Humanflow owner modules it uses; it needs no monorepo
paths or fleet CPU script for the supported commands. Rendering uses a pinned HyperFrames release and
downloads GSAP from its pinned CDN URL; an offline render is not promised.
The flat capture adapters group each label under one timed element. HyperFrames
may warn that these groups could use sub-compositions for Studio organization;
the groups retain their own timing and animate untimed children.

Only the selected owners and original sample are exported. Hosted orchestration,
provider generation, the production database and the human editor are outside
this release. `SOURCE-MANIFEST.json` records the source file hashes and notices.
Generated recordings and renders are excluded from git.
